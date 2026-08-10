import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import MagicMock, patch

from motor_noticias.collectors.html_municipio_libertador import (
    HEADERS,
    ErrorRecoleccionHTML,
    MunicipioLibertadorHTMLCollector,
    parsear_html,
)
from motor_noticias.db import Database
from motor_noticias.pipeline import ejecutar_pipeline
from motor_noticias.redaccion.mock import RedactorMock

FIXTURE_PATH = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "fixtures"
    / "municipio_libertador_html_prueba.html"
)
NOMBRE_FUENTE = "Municipalidad de Libertador General San Martín"
URL_BASE = "https://municipiolgsmjujuy.gob.ar/actividades-intendente"


class ColectorHTMLDePrueba:
    """Envuelve el fixture HTML local. No realiza ninguna conexión de red."""

    def __init__(self, contenido):
        self.contenido = contenido

    def recolectar(self):
        return parsear_html(self.contenido, URL_BASE, NOMBRE_FUENTE)


class TestParsearHTML(unittest.TestCase):
    def setUp(self):
        self.contenido = FIXTURE_PATH.read_text(encoding="utf-8")

    def test_extrae_las_publicaciones_de_la_seccion_principal(self):
        noticias = parsear_html(self.contenido, URL_BASE, NOMBRE_FUENTE)
        self.assertEqual(len(noticias), 3)

    def test_extrae_los_campos_minimos(self):
        noticias = parsear_html(self.contenido, URL_BASE, NOMBRE_FUENTE)
        primera = noticias[0]
        self.assertIn("entrega de viviendas", primera["titulo"])
        self.assertTrue(primera["url"].startswith("https://municipiolgsmjujuy.gob.ar/"))
        self.assertEqual(primera["fuente"], NOMBRE_FUENTE)
        self.assertEqual(primera["fecha"], "2026-08-01")
        self.assertTrue(primera["texto"])

    def test_no_captura_enlaces_de_navegacion_ni_pie_de_pagina(self):
        noticias = parsear_html(self.contenido, URL_BASE, NOMBRE_FUENTE)
        titulos = [n["titulo"] for n in noticias]
        for titulo_navegacion in ("Inicio", "Turismo", "Contacto", "Prensa"):
            self.assertNotIn(titulo_navegacion, titulos)


class TestPipelineConFixtureHTML(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmpdir.name) / "test.db")
        self.redactor = RedactorMock()
        self.collector = ColectorHTMLDePrueba(FIXTURE_PATH.read_text(encoding="utf-8"))

    def tearDown(self):
        self.db.close()
        self.tmpdir.cleanup()

    def test_pipeline_offline_sobre_fixture_html(self):
        resultados = ejecutar_pipeline(self.db, self.collector, self.redactor)
        self.assertEqual(len(resultados), 3)

        self.assertEqual(resultados[0][1], "preparada")
        self.assertEqual(resultados[1][1], "preparada")
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

    @patch("motor_noticias.collectors.html_municipio_libertador.urllib.request.urlopen")
    def test_usa_request_con_headers_en_lugar_de_url_cruda(self, urlopen_mock):
        urlopen_mock.return_value = self._respuesta_falsa(self.contenido_fixture)
        collector = MunicipioLibertadorHTMLCollector()

        noticias = collector.recolectar()

        urlopen_mock.assert_called_once()
        peticion_enviada = urlopen_mock.call_args.args[0]
        self.assertIsInstance(peticion_enviada, urllib.request.Request)
        self.assertEqual(peticion_enviada.full_url, collector.url)
        for clave, valor in HEADERS.items():
            self.assertEqual(peticion_enviada.get_header(clave.capitalize()), valor)
        self.assertEqual(len(noticias), 3)

    @patch("motor_noticias.collectors.html_municipio_libertador.urllib.request.urlopen")
    def test_http_error_se_convierte_en_error_controlado(self, urlopen_mock):
        urlopen_mock.side_effect = urllib.error.HTTPError(
            url=URL_BASE, code=403, msg="Forbidden", hdrs=None, fp=None
        )
        collector = MunicipioLibertadorHTMLCollector()

        with self.assertRaises(ErrorRecoleccionHTML) as contexto:
            collector.recolectar()
        self.assertIn("403", str(contexto.exception))

    @patch("motor_noticias.collectors.html_municipio_libertador.urllib.request.urlopen")
    def test_url_error_se_convierte_en_error_controlado(self, urlopen_mock):
        urlopen_mock.side_effect = urllib.error.URLError("nombre no resuelto")
        collector = MunicipioLibertadorHTMLCollector()

        with self.assertRaises(ErrorRecoleccionHTML):
            collector.recolectar()


if __name__ == "__main__":
    unittest.main()
