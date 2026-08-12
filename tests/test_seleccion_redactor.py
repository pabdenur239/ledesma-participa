import json
import tempfile
import unittest
from pathlib import Path
from typing import Tuple
from unittest.mock import patch

from motor_noticias import cli, continuo_runner
from motor_noticias.db import Database
from motor_noticias.ingreso_manual import cargar_noticia_manual
from motor_noticias.models import Noticia
from motor_noticias.panel.server import PanelHandler
from motor_noticias.pipeline import ejecutar_pipeline
from motor_noticias.redaccion import ErrorConfiguracionRedactor, crear_redactor
from motor_noticias.redaccion.base import Redactor
from motor_noticias.redaccion.mock import RedactorMock
from motor_noticias.redaccion.ollama import RedactorOllama

import run_panel

TEXTO_LOCAL = (
    "Vecinos de Libertador General San Martín reclamaron por el estado de una plaza del barrio "
    "y pidieron a la Municipalidad que intervenga antes de que empiecen las lluvias."
)


class _RedactorEspia(Redactor):
    """Redactor de prueba que registra si fue invocado, sin tocar red."""

    def __init__(self):
        self.llamadas = 0

    def redactar(self, noticia: Noticia) -> Tuple[str, str]:
        self.llamadas += 1
        return f"[espía] {noticia.titulo_original}", f"[espía] {noticia.texto_original}"


class _ColectorDePrueba:
    def __init__(self, items):
        self.items = items

    def recolectar(self):
        return self.items


def _escribir_config(tmp: Path, proveedor) -> Path:
    ruta = tmp / "redaccion.json"
    contenido = {} if proveedor is None else {"proveedor": proveedor}
    ruta.write_text(json.dumps(contenido), encoding="utf-8")
    return ruta


class TestPrecedenciaYValidacion(unittest.TestCase):
    """`crear_redactor`: 1) override explícito, 2) config/redaccion.json →
    "proveedor", 3) validación, 4) instanciación. Todo con archivos de
    config temporales para no depender ni mutar el config real del repo."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.tmp = Path(self.tmpdir.name)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_sin_override_usa_configuracion_comun(self):
        config_ollama = _escribir_config(self.tmp, "ollama")
        self.assertIsInstance(crear_redactor(config_path=config_ollama), RedactorOllama)

        config_mock = _escribir_config(self.tmp, "mock")
        self.assertIsInstance(crear_redactor(config_path=config_mock), RedactorMock)

    def test_sin_config_ni_override_cae_a_mock_por_seguridad(self):
        # archivo inexistente: nunca se asume Ollama sin una configuración explícita
        self.assertIsInstance(crear_redactor(config_path=self.tmp / "no-existe.json"), RedactorMock)

    # 4. --redactor mock sobrescribe configuración
    def test_override_mock_pisa_configuracion_ollama(self):
        config_ollama = _escribir_config(self.tmp, "ollama")
        self.assertIsInstance(crear_redactor("mock", config_path=config_ollama), RedactorMock)

    # 5. --redactor ollama sobrescribe configuración
    def test_override_ollama_pisa_configuracion_mock(self):
        config_mock = _escribir_config(self.tmp, "mock")
        self.assertIsInstance(crear_redactor("ollama", config_path=config_mock), RedactorOllama)

    # 6. valor inválido da error claro
    def test_override_invalido_da_error_claro(self):
        with self.assertRaises(ErrorConfiguracionRedactor) as contexto:
            crear_redactor("invalido")
        self.assertIn("invalido", str(contexto.exception))
        self.assertIn("mock", str(contexto.exception))
        self.assertIn("ollama", str(contexto.exception))

    def test_configuracion_con_valor_invalido_da_error_claro(self):
        config_invalida = _escribir_config(self.tmp, "chatgpt")
        with self.assertRaises(ErrorConfiguracionRedactor):
            crear_redactor(config_path=config_invalida)

    # 7. tests offline no llaman Ollama (construir no hace red; nunca se llama .redactar())
    def test_crear_redactor_ollama_no_hace_red_al_instanciar(self):
        with patch("urllib.request.urlopen") as urlopen_mock:
            redactor = crear_redactor("ollama")
        self.assertIsInstance(redactor, RedactorOllama)
        urlopen_mock.assert_not_called()


class TestEntryPointsUsanLaConfiguracionComun(unittest.TestCase):
    """Los tres entry points comparten la MISMA config/redaccion.json real
    del repo (que en este proyecto trae "proveedor": "ollama"): sin pasar
    --redactor, los tres deben resolver a RedactorOllama. Se intercepta el
    consumidor final de cada uno (nunca se ejecuta un ciclo real ni se abre
    un socket) para no depender de red ni de un servidor Ollama corriendo."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmpdir.cleanup()

    # 1. configuración común = ollama → run.py usa Ollama
    def test_run_py_usa_ollama_sin_override(self):
        capturado = {}

        def _espia(db, collector, redactor):
            capturado["redactor"] = redactor
            return []

        db_path = Path(self.tmpdir.name) / "cli.db"
        argv = ["run.py", "--db", str(db_path), "--fuente", "fixture"]
        with patch("motor_noticias.cli.ejecutar_pipeline", side_effect=_espia), patch("sys.argv", argv):
            cli.main()

        self.assertIsInstance(capturado["redactor"], RedactorOllama)

    # 4/5 (variante para run.py): --redactor mock sobrescribe la config común
    def test_run_py_override_mock_pisa_configuracion(self):
        capturado = {}

        def _espia(db, collector, redactor):
            capturado["redactor"] = redactor
            return []

        db_path = Path(self.tmpdir.name) / "cli2.db"
        argv = ["run.py", "--db", str(db_path), "--fuente", "fixture", "--redactor", "mock"]
        with patch("motor_noticias.cli.ejecutar_pipeline", side_effect=_espia), patch("sys.argv", argv):
            cli.main()

        self.assertIsInstance(capturado["redactor"], RedactorMock)

    # 2. configuración común = ollama → run_continuo.py usa Ollama
    def test_run_continuo_py_usa_ollama_sin_override(self):
        capturado = {}

        def _espia(db, redactor, intervalo_segundos, max_ciclos=None, dormir=None):
            capturado["redactor"] = redactor

        db_path = Path(self.tmpdir.name) / "continuo.db"
        lock_path = Path(self.tmpdir.name) / "continuo.lock"
        log_path = Path(self.tmpdir.name) / "continuo.log"
        argv = ["--db", str(db_path), "--lock", str(lock_path), "--log", str(log_path), "--max-ciclos", "1"]
        with patch("motor_noticias.continuo_runner.bucle_continuo", side_effect=_espia):
            continuo_runner.main(argv)

        self.assertIsInstance(capturado["redactor"], RedactorOllama)

    # 3. configuración común = ollama → run_panel.py usa Ollama
    def test_run_panel_py_usa_ollama_sin_override(self):
        capturado = {}

        def _espia(db_path=None, redactor=None):
            capturado["redactor"] = redactor

        with patch("run_panel.iniciar_servidor", side_effect=_espia), patch("sys.argv", ["run_panel.py"]):
            run_panel.main()

        self.assertIsInstance(capturado["redactor"], RedactorOllama)

    # 8. carga manual y automática usan la misma configuración por defecto
    def test_automatica_y_manual_resuelven_el_mismo_redactor_por_defecto(self):
        capturado_cli = {}

        def _espia_cli(db, collector, redactor):
            capturado_cli["redactor"] = redactor
            return []

        db_path = Path(self.tmpdir.name) / "mismo.db"
        argv = ["run.py", "--db", str(db_path), "--fuente", "fixture"]
        with patch("motor_noticias.cli.ejecutar_pipeline", side_effect=_espia_cli), patch("sys.argv", argv):
            cli.main()

        capturado_panel = {}

        def _espia_panel(db_path=None, redactor=None):
            capturado_panel["redactor"] = redactor

        with patch("run_panel.iniciar_servidor", side_effect=_espia_panel), patch("sys.argv", ["run_panel.py"]):
            run_panel.main()

        self.assertIs(type(capturado_cli["redactor"]), type(capturado_panel["redactor"]))
        self.assertIsInstance(capturado_panel["redactor"], RedactorOllama)


class TestPanelSinHardcodeDeMock(unittest.TestCase):
    def test_panel_redactor_por_defecto_de_clase_es_seguro_sin_config(self):
        # El default de clase (usado si algo instancia PanelHandler sin pasar
        # por iniciar_servidor, p.ej. otros tests) es explícitamente mock:
        # no depende de leer config al importar el módulo.
        self.assertIsInstance(PanelHandler.redactor, RedactorMock)

    def test_iniciar_servidor_sin_override_resuelve_configuracion_comun(self):
        with patch("motor_noticias.panel.server.HTTPServer"):
            from motor_noticias.panel.server import iniciar_servidor

            iniciar_servidor()
        try:
            self.assertIsInstance(PanelHandler.redactor, RedactorOllama)
        finally:
            PanelHandler.redactor = crear_redactor("mock")  # no afectar el resto de la suite

    def test_iniciar_servidor_con_override_explicito_no_lee_configuracion(self):
        redactor_explicito = RedactorMock()
        with patch("motor_noticias.panel.server.HTTPServer"):
            from motor_noticias.panel.server import iniciar_servidor

            iniciar_servidor(redactor=redactor_explicito)
        self.assertIs(PanelHandler.redactor, redactor_explicito)


class TestIngresoManualUsaElRedactorRecibido(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmpdir.name) / "test.db")

    def tearDown(self):
        self.db.close()
        self.tmpdir.cleanup()

    # ingreso manual recibe el redactor configurado (no uno hardcodeado adentro)
    def test_ingreso_manual_usa_el_redactor_que_recibe(self):
        espia = _RedactorEspia()
        with patch("motor_noticias.ingreso_manual.generar_agenda"):
            resultado = cargar_noticia_manual(self.db, espia, fuente="Ledesma Soy", texto=TEXTO_LOCAL)

        self.assertEqual(espia.llamadas, 1)
        noticia = self.db.obtener(resultado.noticia_id)
        self.assertTrue(noticia["titulo_preparado"].startswith("[espía]"))

    # modo mock funciona offline
    def test_modo_mock_funciona_offline(self):
        with patch("urllib.request.urlopen") as urlopen_mock, patch(
            "motor_noticias.ingreso_manual.generar_agenda"
        ):
            resultado = cargar_noticia_manual(
                self.db, RedactorMock(), fuente="Ledesma Soy", texto=TEXTO_LOCAL
            )
        urlopen_mock.assert_not_called()
        self.assertEqual(resultado.resultado_pipeline, "preparada")

    # mismo tipo de procesamiento para noticia automática y manual
    def test_mismo_procesamiento_para_automatica_y_manual(self):
        espia_automatica = _RedactorEspia()
        espia_manual = _RedactorEspia()

        collector = _ColectorDePrueba(
            [
                {
                    "titulo": "Obras en Libertador General San Martín",
                    "texto": TEXTO_LOCAL,
                    "url": "https://ejemplo.test/automatica-1",
                    "fuente": "Fuente de prueba",
                    "fecha": "",
                }
            ]
        )
        resultados_auto = ejecutar_pipeline(self.db, collector, espia_automatica)
        with patch("motor_noticias.ingreso_manual.generar_agenda"):
            resultado_manual = cargar_noticia_manual(
                self.db, espia_manual, fuente="Ledesma Soy", texto=TEXTO_LOCAL + " Nota distinta."
            )

        noticia_auto = resultados_auto[0][0]
        noticia_manual = self.db.obtener(resultado_manual.noticia_id)

        # ambas pasaron por el mismo pipeline (procesar_noticia): mismo tipo
        # de resultado, mismo formato de título/texto preparado (vía el
        # redactor recibido, sin caminos alternativos).
        self.assertEqual(espia_automatica.llamadas, 1)
        self.assertEqual(espia_manual.llamadas, 1)
        self.assertEqual(noticia_auto.estado, "preparada")
        self.assertEqual(noticia_manual["estado"], "preparada")
        self.assertTrue(noticia_auto.titulo_preparado.startswith("[espía]"))
        self.assertTrue(noticia_manual["titulo_preparado"].startswith("[espía]"))
        self.assertEqual(noticia_auto.origen_ingreso, "automatico")
        self.assertEqual(noticia_manual["origen_ingreso"], "manual")


if __name__ == "__main__":
    unittest.main()
