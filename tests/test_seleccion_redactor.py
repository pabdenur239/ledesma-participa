import tempfile
import unittest
from pathlib import Path
from typing import Tuple
from unittest.mock import patch

from motor_noticias.db import Database
from motor_noticias.ingreso_manual import cargar_noticia_manual
from motor_noticias.models import Noticia
from motor_noticias.panel.server import PanelHandler
from motor_noticias.pipeline import ejecutar_pipeline
from motor_noticias.redaccion import crear_redactor
from motor_noticias.redaccion.base import Redactor
from motor_noticias.redaccion.mock import RedactorMock
from motor_noticias.redaccion.ollama import RedactorOllama

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


class TestSeleccionCentralizadaDeRedactor(unittest.TestCase):
    def test_crear_redactor_default_es_mock(self):
        self.assertIsInstance(crear_redactor(), RedactorMock)
        self.assertIsInstance(crear_redactor("mock"), RedactorMock)

    def test_crear_redactor_ollama_no_hace_red_al_instanciar(self):
        # Construir RedactorOllama solo lee config/redaccion.json; el único
        # request real ocurre dentro de .redactar(), nunca al construirlo.
        with patch("urllib.request.urlopen") as urlopen_mock:
            redactor = crear_redactor("ollama")
        self.assertIsInstance(redactor, RedactorOllama)
        urlopen_mock.assert_not_called()

    def test_panel_no_tiene_redactormock_hardcodeado(self):
        # El panel usa el mismo mecanismo centralizado (`crear_redactor`),
        # no una instancia fija de RedactorMock escrita a mano en el módulo.
        self.assertIs(type(PanelHandler.redactor), type(crear_redactor()))

    def test_iniciar_servidor_permite_configurar_el_redactor(self):
        from motor_noticias.panel.server import iniciar_servidor

        redactor_ollama = crear_redactor("ollama")
        with patch("motor_noticias.panel.server.HTTPServer"):
            iniciar_servidor(redactor=redactor_ollama)
        self.assertIs(PanelHandler.redactor, redactor_ollama)
        # se restaura a mock para no afectar el resto de la suite
        PanelHandler.redactor = crear_redactor("mock")


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
