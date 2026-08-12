import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import MagicMock, patch

from motor_noticias.collectors.rss_todojujuy import (
    HEADERS,
    ErrorRecoleccionTodoJujuy,
    TodoJujuyRSSCollector,
    parsear_rss,
)
from motor_noticias.db import Database
from motor_noticias.pipeline import ejecutar_pipeline
from motor_noticias.redaccion.mock import RedactorMock

FIXTURE_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "fixtures" / "todojujuy_rss_prueba.xml"
)
NOMBRE_FUENTE = "TodoJujuy"

TITULO_CONCEJO = "El Concejo Deliberante de Libertador General San Martín debatió el presupuesto 2026"
TITULO_FRAILE_PINTADO = "Fraile Pintado inauguró una nueva plaza de juegos infantiles"
TITULO_PROVINCIAL = "El Gobierno provincial presentó el calendario turístico de la temporada"


class ColectorRSSDePrueba:
    """Envuelve el fixture XML local. No realiza ninguna conexión de red."""

    def __init__(self, contenido: bytes):
        self.contenido = contenido

    def recolectar(self):
        return parsear_rss(self.contenido, NOMBRE_FUENTE)


class TestParsearRSS(unittest.TestCase):
    def setUp(self):
        self.contenido = FIXTURE_PATH.read_bytes()

    def test_extrae_las_noticias_reales_incluido_el_duplicado(self):
        noticias = parsear_rss(self.contenido, NOMBRE_FUENTE)
        titulos = [n["titulo"] for n in noticias]
        self.assertEqual(len(noticias), 4)  # incluye el duplicado, filtrado luego por el pipeline
        self.assertIn(TITULO_CONCEJO, titulos)
        self.assertIn(TITULO_FRAILE_PINTADO, titulos)
        self.assertIn(TITULO_PROVINCIAL, titulos)

    def test_extrae_titulo_resumen_url_fecha_y_fuente(self):
        noticias = parsear_rss(self.contenido, NOMBRE_FUENTE)
        concejo = next(n for n in noticias if n["titulo"] == TITULO_CONCEJO)
        self.assertEqual(
            concejo["texto"],
            "Los concejales analizaron el proyecto de presupuesto municipal para el "
            "próximo año en una sesión extendida del Concejo Deliberante.",
        )
        self.assertEqual(
            concejo["url"],
            "https://www.todojujuy.com/jujuy/concejo-deliberante-libertador-debatio-presupuesto-2026-n300001",
        )
        self.assertEqual(concejo["fecha"], "Wed, 12 Aug 2026 13:22:29 -0300")
        self.assertEqual(concejo["fuente"], NOMBRE_FUENTE)

    def test_extrae_imagen_desde_enclosure(self):
        noticias = parsear_rss(self.contenido, NOMBRE_FUENTE)
        concejo = next(n for n in noticias if n["titulo"] == TITULO_CONCEJO)
        self.assertEqual(
            concejo["imagen_url"],
            "https://media.todojujuy.com/p/aaa111/imagenes/concejo-libertador.jpg",
        )

    def test_imagen_vacia_cuando_no_hay_enclosure(self):
        noticias = parsear_rss(self.contenido, NOMBRE_FUENTE)
        fraile_pintado = next(n for n in noticias if n["titulo"] == TITULO_FRAILE_PINTADO)
        self.assertIsNone(fraile_pintado["imagen_url"])


class TestPipelineConFixtureRSS(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmpdir.name) / "test.db")
        self.redactor = RedactorMock()
        self.contenido = FIXTURE_PATH.read_bytes()

    def tearDown(self):
        self.db.close()
        self.tmpdir.cleanup()

    def test_noticia_local_relevante_con_riesgo_institucional_por_concejo(self):
        resultados = ejecutar_pipeline(self.db, ColectorRSSDePrueba(self.contenido), self.redactor)
        noticia_concejo, resultado = next(
            (n, r) for n, r in resultados if n.titulo_original == TITULO_CONCEJO
        )
        self.assertEqual(resultado, "preparada")
        self.assertTrue(noticia_concejo.relevancia_local)
        self.assertTrue(noticia_concejo.tiene_imagen_original)
        self.assertTrue(noticia_concejo.requiere_revision_especial)

    def test_noticia_local_sin_imagen_usa_placa(self):
        resultados = ejecutar_pipeline(self.db, ColectorRSSDePrueba(self.contenido), self.redactor)
        noticia_fraile_pintado, resultado = next(
            (n, r) for n, r in resultados if n.titulo_original == TITULO_FRAILE_PINTADO
        )
        self.assertEqual(resultado, "preparada")
        self.assertTrue(noticia_fraile_pintado.relevancia_local)
        self.assertFalse(noticia_fraile_pintado.tiene_imagen_original)

    def test_noticia_provincial_ajena_queda_descartada(self):
        resultados = ejecutar_pipeline(self.db, ColectorRSSDePrueba(self.contenido), self.redactor)
        noticia_provincial, resultado = next(
            (n, r) for n, r in resultados if n.titulo_original == TITULO_PROVINCIAL
        )
        self.assertEqual(resultado, "descartada")
        self.assertFalse(noticia_provincial.relevancia_local)

    def test_duplicado_no_se_almacena_dos_veces(self):
        resultados = ejecutar_pipeline(self.db, ColectorRSSDePrueba(self.contenido), self.redactor)
        self.assertEqual(resultados[3][1], "duplicado")
        self.assertEqual(len(self.db.listar()), 3)

    def test_segunda_ejecucion_detecta_duplicados(self):
        ejecutar_pipeline(self.db, ColectorRSSDePrueba(self.contenido), self.redactor)
        self.assertEqual(len(self.db.listar()), 3)

        segunda = ejecutar_pipeline(self.db, ColectorRSSDePrueba(self.contenido), self.redactor)
        for _, resultado in segunda:
            self.assertEqual(resultado, "duplicado")
        self.assertEqual(len(self.db.listar()), 3)


class TestPeticionHTTP(unittest.TestCase):
    """Verifica la construcción de la petición HTTP sin acceder a la red real."""

    def setUp(self):
        self.contenido_fixture = FIXTURE_PATH.read_bytes()

    def _respuesta_falsa(self, contenido):
        respuesta = MagicMock()
        respuesta.read.return_value = contenido
        respuesta.__enter__.return_value = respuesta
        respuesta.__exit__.return_value = False
        return respuesta

    @patch("motor_noticias.collectors.rss_todojujuy.urllib.request.urlopen")
    def test_usa_request_con_headers_en_lugar_de_url_cruda(self, urlopen_mock):
        urlopen_mock.return_value = self._respuesta_falsa(self.contenido_fixture)
        collector = TodoJujuyRSSCollector()

        noticias = collector.recolectar()

        urlopen_mock.assert_called_once()
        peticion_enviada = urlopen_mock.call_args.args[0]
        self.assertIsInstance(peticion_enviada, urllib.request.Request)
        self.assertEqual(peticion_enviada.full_url, collector.url)
        for clave, valor in HEADERS.items():
            self.assertEqual(peticion_enviada.get_header(clave.capitalize()), valor)
        self.assertEqual(len(noticias), 4)

    @patch("motor_noticias.collectors.rss_todojujuy.urllib.request.urlopen")
    def test_http_error_se_convierte_en_error_controlado(self, urlopen_mock):
        urlopen_mock.side_effect = urllib.error.HTTPError(
            url="https://www.todojujuy.com/rss/pages/jujuy.xml",
            code=403,
            msg="Forbidden",
            hdrs=None,
            fp=None,
        )
        collector = TodoJujuyRSSCollector()

        with self.assertRaises(ErrorRecoleccionTodoJujuy) as contexto:
            collector.recolectar()
        self.assertIn("403", str(contexto.exception))

    @patch("motor_noticias.collectors.rss_todojujuy.urllib.request.urlopen")
    def test_url_error_se_convierte_en_error_controlado(self, urlopen_mock):
        urlopen_mock.side_effect = urllib.error.URLError("nombre no resuelto")
        collector = TodoJujuyRSSCollector()

        with self.assertRaises(ErrorRecoleccionTodoJujuy):
            collector.recolectar()


if __name__ == "__main__":
    unittest.main()
