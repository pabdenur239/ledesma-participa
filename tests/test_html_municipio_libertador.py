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
    extraer_actividades,
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
LOCALIDAD = "Libertador General San Martín"

MARCADOR_BLOQUE = "Actividades sr. Intendente Ing. Oscar Jayat"
TITULO_BRIPAEM = "Ing. Oscar Jayat nuevo Presidente del BRIPAEM"
RESUMEN_BRIPAEM = (
    "En una asamblea extraordinaria realizada en la ciudad de Buenos Aires, "
    "asumió como Presidente del BRIPAEM por el periodo 2026-2028."
)
TITULO_POLIDEPORTIVO = "Reinauguración Polideportivo del Barrio 18 de Noviembre"
TITULO_CONVENIO = "Firma de Convenio Etapa 2 Techado del Predio Ferial Municipal"


class ColectorHTMLDePrueba:
    """Envuelve el fixture HTML local. No realiza ninguna conexión de red."""

    def __init__(self, contenido):
        self.contenido = contenido

    def recolectar(self):
        return extraer_actividades(self.contenido, URL_BASE, NOMBRE_FUENTE, LOCALIDAD)


class TestExtraerActividades(unittest.TestCase):
    def setUp(self):
        self.contenido = FIXTURE_PATH.read_text(encoding="utf-8")

    def test_decodifica_html_escapado_y_encuentra_la_primera_actividad(self):
        actividades = extraer_actividades(self.contenido, URL_BASE, NOMBRE_FUENTE, LOCALIDAD)
        titulos = [a["titulo"] for a in actividades]
        self.assertIn(TITULO_BRIPAEM, titulos)

    def test_el_encabezado_del_bloque_no_genera_actividad(self):
        actividades = extraer_actividades(self.contenido, URL_BASE, NOMBRE_FUENTE, LOCALIDAD)
        titulos = [a["titulo"] for a in actividades]
        self.assertNotIn(MARCADOR_BLOQUE, titulos)

    def test_el_resumen_bripaem_no_genera_actividad_independiente(self):
        # el resumen real está envuelto en un h4 (no un <p>), que es
        # exactamente el patrón que en producción se coló como noticia.
        actividades = extraer_actividades(self.contenido, URL_BASE, NOMBRE_FUENTE, LOCALIDAD)
        titulos = [a["titulo"] for a in actividades]
        self.assertNotIn(RESUMEN_BRIPAEM, titulos)

    def test_titulo_y_resumen_bripaem_forman_un_unico_registro(self):
        actividades = extraer_actividades(self.contenido, URL_BASE, NOMBRE_FUENTE, LOCALIDAD)
        coincidencias = [a for a in actividades if a["titulo"] == TITULO_BRIPAEM]
        self.assertEqual(len(coincidencias), 1)
        self.assertEqual(coincidencias[0]["texto"], RESUMEN_BRIPAEM)

    def test_encuentra_las_otras_actividades(self):
        actividades = extraer_actividades(self.contenido, URL_BASE, NOMBRE_FUENTE, LOCALIDAD)
        titulos = [a["titulo"] for a in actividades]
        self.assertIn(TITULO_POLIDEPORTIVO, titulos)
        self.assertIn(TITULO_CONVENIO, titulos)
        self.assertEqual(len(actividades), 3)

    def test_todas_las_actividades_tienen_la_localidad_del_municipio(self):
        actividades = extraer_actividades(self.contenido, URL_BASE, NOMBRE_FUENTE, LOCALIDAD)
        for actividad in actividades:
            self.assertEqual(actividad["localidad"], LOCALIDAD)

    def test_ignora_navegacion_pie_de_pagina_y_datos_de_contacto(self):
        actividades = extraer_actividades(self.contenido, URL_BASE, NOMBRE_FUENTE, LOCALIDAD)
        titulos = [a["titulo"] for a in actividades]
        for texto_no_deseado in (
            "Inicio",
            "Turismo",
            "Contacto",
            "Prensa",
            MARCADOR_BLOQUE,
        ):
            self.assertNotIn(texto_no_deseado, titulos)
        for actividad in actividades:
            self.assertNotIn("Domicilio", actividad["texto"])
            self.assertNotIn("Teléfono", actividad["texto"])
            self.assertNotIn("@", actividad["texto"])

    def test_genera_identificadores_estables_y_distintos(self):
        actividades = extraer_actividades(self.contenido, URL_BASE, NOMBRE_FUENTE, LOCALIDAD)
        urls = [a["url"] for a in actividades]

        self.assertEqual(len(urls), len(set(urls)))
        for url in urls:
            self.assertTrue(url.startswith(f"{URL_BASE}#"))

        otra_pasada = extraer_actividades(self.contenido, URL_BASE, NOMBRE_FUENTE, LOCALIDAD)
        self.assertEqual(urls, [a["url"] for a in otra_pasada])


class TestPipelineConFixtureHTML(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmpdir.name) / "test.db")
        self.redactor = RedactorMock()
        self.contenido = FIXTURE_PATH.read_text(encoding="utf-8")

    def tearDown(self):
        self.db.close()
        self.tmpdir.cleanup()

    def test_actividades_municipales_quedan_preparadas_por_su_localidad(self):
        resultados = ejecutar_pipeline(self.db, ColectorHTMLDePrueba(self.contenido), self.redactor)
        self.assertEqual(len(resultados), 3)
        for noticia, resultado in resultados:
            self.assertEqual(resultado, "preparada")
            self.assertEqual(noticia.localidad, LOCALIDAD)
            self.assertTrue(noticia.relevancia_local)
        # las tres actividades comparten la misma URL de página; ninguna debe
        # perderse por ser confundida con un duplicado de otra.
        self.assertEqual(len(self.db.listar()), 3)

    def test_segunda_ejecucion_detecta_duplicados(self):
        ejecutar_pipeline(self.db, ColectorHTMLDePrueba(self.contenido), self.redactor)
        self.assertEqual(len(self.db.listar()), 3)

        segunda = ejecutar_pipeline(self.db, ColectorHTMLDePrueba(self.contenido), self.redactor)
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

    @patch("motor_noticias.collectors.html_municipio_libertador.urllib.request.urlopen")
    def test_usa_request_con_headers_en_lugar_de_url_cruda(self, urlopen_mock):
        urlopen_mock.return_value = self._respuesta_falsa(self.contenido_fixture)
        collector = MunicipioLibertadorHTMLCollector()

        actividades = collector.recolectar()

        urlopen_mock.assert_called_once()
        peticion_enviada = urlopen_mock.call_args.args[0]
        self.assertIsInstance(peticion_enviada, urllib.request.Request)
        self.assertEqual(peticion_enviada.full_url, collector.url)
        for clave, valor in HEADERS.items():
            self.assertEqual(peticion_enviada.get_header(clave.capitalize()), valor)
        self.assertEqual(len(actividades), 3)

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
