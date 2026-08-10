import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import MagicMock, patch

from motor_noticias.collectors.rss_prensa_jujuy import (
    HEADERS,
    ErrorRecoleccionRSS,
    PrensaJujuyRSSCollector,
    parsear_rss,
)
from motor_noticias.db import Database
from motor_noticias.pipeline import ejecutar_pipeline
from motor_noticias.redaccion.mock import RedactorMock

FIXTURE_PATH = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "fixtures"
    / "prensa_jujuy_rss_prueba.xml"
)
NOMBRE_FUENTE = "Prensa Jujuy (Gobierno de Jujuy)"


class ColectorRSSDePrueba:
    """Envuelve el fixture XML local. No realiza ninguna conexión de red."""

    def __init__(self, contenido):
        self.contenido = contenido

    def recolectar(self):
        return parsear_rss(self.contenido, NOMBRE_FUENTE)


class TestParsearRSS(unittest.TestCase):
    def setUp(self):
        self.contenido = FIXTURE_PATH.read_bytes()

    def test_parsea_los_items_del_fixture(self):
        noticias = parsear_rss(self.contenido, NOMBRE_FUENTE)
        self.assertEqual(len(noticias), 3)

    def test_extrae_los_campos_minimos(self):
        noticias = parsear_rss(self.contenido, NOMBRE_FUENTE)
        primera = noticias[0]
        self.assertIn("Libertador", primera["titulo"])
        self.assertTrue(primera["url"].startswith("https://"))
        self.assertEqual(primera["fuente"], NOMBRE_FUENTE)
        self.assertTrue(primera["fecha"])
        self.assertTrue(primera["texto"])
        self.assertNotIn("<p>", primera["texto"])


class TestPipelineConFixtureRSS(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmpdir.name) / "test.db")
        self.redactor = RedactorMock()
        self.collector = ColectorRSSDePrueba(FIXTURE_PATH.read_bytes())

    def tearDown(self):
        self.db.close()
        self.tmpdir.cleanup()

    def test_pipeline_offline_sobre_fixture_rss(self):
        resultados = ejecutar_pipeline(self.db, self.collector, self.redactor)
        self.assertEqual(len(resultados), 3)

        self.assertEqual(resultados[0][1], "preparada")
        self.assertEqual(resultados[1][1], "descartada")
        self.assertEqual(resultados[2][1], "duplicado")

        self.assertEqual(len(self.db.listar()), 2)


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

    @patch("motor_noticias.collectors.rss_prensa_jujuy.urllib.request.urlopen")
    def test_usa_request_con_headers_en_lugar_de_url_cruda(self, urlopen_mock):
        urlopen_mock.return_value = self._respuesta_falsa(self.contenido_fixture)
        collector = PrensaJujuyRSSCollector()

        noticias = collector.recolectar()

        urlopen_mock.assert_called_once()
        peticion_enviada = urlopen_mock.call_args.args[0]
        self.assertIsInstance(peticion_enviada, urllib.request.Request)
        self.assertEqual(peticion_enviada.full_url, collector.url)
        for clave, valor in HEADERS.items():
            self.assertEqual(peticion_enviada.get_header(clave.capitalize()), valor)
        self.assertEqual(len(noticias), 3)

    @patch("motor_noticias.collectors.rss_prensa_jujuy.urllib.request.urlopen")
    def test_http_error_se_convierte_en_error_controlado(self, urlopen_mock):
        urlopen_mock.side_effect = urllib.error.HTTPError(
            url="https://prensa.jujuy.gob.ar/rss/ultimas-noticias.xml",
            code=403,
            msg="Forbidden",
            hdrs=None,
            fp=None,
        )
        collector = PrensaJujuyRSSCollector()

        with self.assertRaises(ErrorRecoleccionRSS) as contexto:
            collector.recolectar()
        self.assertIn("403", str(contexto.exception))

    @patch("motor_noticias.collectors.rss_prensa_jujuy.urllib.request.urlopen")
    def test_url_error_se_convierte_en_error_controlado(self, urlopen_mock):
        urlopen_mock.side_effect = urllib.error.URLError("nombre no resuelto")
        collector = PrensaJujuyRSSCollector()

        with self.assertRaises(ErrorRecoleccionRSS):
            collector.recolectar()


if __name__ == "__main__":
    unittest.main()
