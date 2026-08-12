import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import MagicMock, patch

from motor_noticias.collectors.rss_somosjujuy import (
    HEADERS,
    ErrorRecoleccionSomosJujuy,
    SomosJujuyRSSCollector,
    parsear_rss,
)
from motor_noticias.db import Database
from motor_noticias.pipeline import ejecutar_pipeline
from motor_noticias.redaccion.mock import RedactorMock

FIXTURE_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "fixtures" / "somosjujuy_rss_prueba.xml"
)
NOMBRE_FUENTE = "Somos Jujuy"

TITULO_CONCEJALES = "Concejales de Libertador General San Martín analizaron el nuevo cronograma de obras"
TITULO_CALILEGUA = "Calilegua celebró su fiesta patronal con numerosas actividades"
TITULO_PROVINCIAL = "El gobierno provincial anunció obras hídricas en San Salvador de Jujuy"


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
        self.assertIn(TITULO_CONCEJALES, titulos)
        self.assertIn(TITULO_CALILEGUA, titulos)
        self.assertIn(TITULO_PROVINCIAL, titulos)

    def test_extrae_titulo_resumen_url_fecha_y_fuente(self):
        noticias = parsear_rss(self.contenido, NOMBRE_FUENTE)
        concejales = next(n for n in noticias if n["titulo"] == TITULO_CONCEJALES)
        self.assertEqual(
            concejales["texto"],
            "El Concejo Deliberante de Libertador General San Martín se reunió "
            "para revisar el avance de las obras previstas para este año.",
        )
        self.assertEqual(
            concejales["url"],
            "https://www.somosjujuy.com.ar/jujuy/concejales-libertador-analizaron-nuevo-cronograma-obras-n300101",
        )
        self.assertEqual(concejales["fecha"], "Wed, 12 Aug 2026 14:45:00 -0300")
        self.assertEqual(concejales["fuente"], NOMBRE_FUENTE)

    def test_extrae_imagen_embebida_en_la_descripcion(self):
        # La imagen no viene en un campo aparte: está embebida como <img
        # src="..."> al principio del HTML de <description>.
        noticias = parsear_rss(self.contenido, NOMBRE_FUENTE)
        concejales = next(n for n in noticias if n["titulo"] == TITULO_CONCEJALES)
        self.assertEqual(
            concejales["imagen_url"],
            "https://statics.somosjujuy.com.ar/2026/08/aaa111.jpg",
        )
        # el resumen no debe conservar la etiqueta <img> ni ningún HTML
        self.assertNotIn("<img", concejales["texto"])
        self.assertNotIn("<p>", concejales["texto"])

    def test_imagen_vacia_cuando_la_descripcion_no_trae_img(self):
        noticias = parsear_rss(self.contenido, NOMBRE_FUENTE)
        calilegua = next(n for n in noticias if n["titulo"] == TITULO_CALILEGUA)
        self.assertIsNone(calilegua["imagen_url"])


class TestPipelineConFixtureRSS(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmpdir.name) / "test.db")
        self.redactor = RedactorMock()
        self.contenido = FIXTURE_PATH.read_bytes()

    def tearDown(self):
        self.db.close()
        self.tmpdir.cleanup()

    def test_noticia_local_relevante_con_riesgo_institucional_por_concejales(self):
        resultados = ejecutar_pipeline(self.db, ColectorRSSDePrueba(self.contenido), self.redactor)
        noticia_concejales, resultado = next(
            (n, r) for n, r in resultados if n.titulo_original == TITULO_CONCEJALES
        )
        self.assertEqual(resultado, "preparada")
        self.assertTrue(noticia_concejales.relevancia_local)
        self.assertTrue(noticia_concejales.tiene_imagen_original)
        self.assertTrue(noticia_concejales.requiere_revision_especial)

    def test_noticia_local_sin_imagen_usa_placa(self):
        resultados = ejecutar_pipeline(self.db, ColectorRSSDePrueba(self.contenido), self.redactor)
        noticia_calilegua, resultado = next(
            (n, r) for n, r in resultados if n.titulo_original == TITULO_CALILEGUA
        )
        self.assertEqual(resultado, "preparada")
        self.assertTrue(noticia_calilegua.relevancia_local)
        self.assertFalse(noticia_calilegua.tiene_imagen_original)

    def test_noticia_provincial_ajena_queda_preparada_sin_relevancia_local(self):
        # Menciona Jujuy sin relación local: territorio "provincial", sin
        # relevancia_local, pero igual queda preparada para que el Motor
        # Editorial en cascada pueda usarla si no hay contenido local/
        # departamental disponible.
        resultados = ejecutar_pipeline(self.db, ColectorRSSDePrueba(self.contenido), self.redactor)
        noticia_provincial, resultado = next(
            (n, r) for n, r in resultados if n.titulo_original == TITULO_PROVINCIAL
        )
        self.assertEqual(resultado, "preparada")
        self.assertEqual(noticia_provincial.territorio, "provincial")
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

    @patch("motor_noticias.collectors.rss_somosjujuy.urllib.request.urlopen")
    def test_usa_request_con_headers_en_lugar_de_url_cruda(self, urlopen_mock):
        urlopen_mock.return_value = self._respuesta_falsa(self.contenido_fixture)
        collector = SomosJujuyRSSCollector()

        noticias = collector.recolectar()

        urlopen_mock.assert_called_once()
        peticion_enviada = urlopen_mock.call_args.args[0]
        self.assertIsInstance(peticion_enviada, urllib.request.Request)
        self.assertEqual(peticion_enviada.full_url, collector.url)
        for clave, valor in HEADERS.items():
            self.assertEqual(peticion_enviada.get_header(clave.capitalize()), valor)
        self.assertEqual(len(noticias), 4)

    @patch("motor_noticias.collectors.rss_somosjujuy.urllib.request.urlopen")
    def test_http_error_se_convierte_en_error_controlado(self, urlopen_mock):
        urlopen_mock.side_effect = urllib.error.HTTPError(
            url="https://www.somosjujuy.com.ar/feed/",
            code=403,
            msg="Forbidden",
            hdrs=None,
            fp=None,
        )
        collector = SomosJujuyRSSCollector()

        with self.assertRaises(ErrorRecoleccionSomosJujuy) as contexto:
            collector.recolectar()
        self.assertIn("403", str(contexto.exception))

    @patch("motor_noticias.collectors.rss_somosjujuy.urllib.request.urlopen")
    def test_url_error_se_convierte_en_error_controlado(self, urlopen_mock):
        urlopen_mock.side_effect = urllib.error.URLError("nombre no resuelto")
        collector = SomosJujuyRSSCollector()

        with self.assertRaises(ErrorRecoleccionSomosJujuy):
            collector.recolectar()


if __name__ == "__main__":
    unittest.main()
