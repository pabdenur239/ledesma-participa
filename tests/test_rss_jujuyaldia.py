import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import MagicMock, patch

from motor_noticias.collectors.rss_jujuyaldia import (
    HEADERS,
    ErrorRecoleccionJujuyAlDia,
    JujuyAlDiaRSSCollector,
    parsear_rss,
)
from motor_noticias.db import Database
from motor_noticias.pipeline import ejecutar_pipeline
from motor_noticias.redaccion.mock import RedactorMock

FIXTURE_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "fixtures" / "jujuyaldia_rss_prueba.xml"
)
NOMBRE_FUENTE = "Jujuy al día"

TITULO_FRAILE_PINTADO = "Atención vecinos de Fraile Pintado: corte de agua programado"
TITULO_CALILEGUA = "Calilegua celebró la semana de la primavera con actividades culturales"
TITULO_PROVINCIAL = "El gobierno provincial anunció el cronograma de pagos de agosto"


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
        self.assertIn(TITULO_FRAILE_PINTADO, titulos)
        self.assertIn(TITULO_CALILEGUA, titulos)
        self.assertIn(TITULO_PROVINCIAL, titulos)

    def test_extrae_titulo_resumen_url_fecha_y_fuente(self):
        noticias = parsear_rss(self.contenido, NOMBRE_FUENTE)
        fraile = next(n for n in noticias if n["titulo"] == TITULO_FRAILE_PINTADO)
        self.assertEqual(
            fraile["texto"],
            "Agua Potable de Jujuy informó que este miércoles habrá un corte programado en "
            "varios barrios de Fraile Pintado por trabajos de mantenimiento.",
        )
        self.assertEqual(
            fraile["url"],
            "https://www.jujuyaldia.com.ar/2026/08/17/atencion-vecinos-fraile-pintado-corte-agua/",
        )
        self.assertEqual(fraile["fecha"], "Mon, 17 Aug 2026 10:00:00 +0000")
        self.assertEqual(fraile["fuente"], NOMBRE_FUENTE)

    def test_extrae_imagen_embebida_en_la_descripcion(self):
        noticias = parsear_rss(self.contenido, NOMBRE_FUENTE)
        fraile = next(n for n in noticias if n["titulo"] == TITULO_FRAILE_PINTADO)
        self.assertEqual(
            fraile["imagen_url"],
            "https://www.jujuyaldia.com.ar/wp-content/uploads/2026/08/corte-agua.jpg",
        )
        self.assertNotIn("<img", fraile["texto"])
        self.assertNotIn("<p>", fraile["texto"])

    def test_imagen_vacia_cuando_la_descripcion_no_trae_img(self):
        noticias = parsear_rss(self.contenido, NOMBRE_FUENTE)
        calilegua = next(n for n in noticias if n["titulo"] == TITULO_CALILEGUA)
        self.assertIsNone(calilegua["imagen_url"])

    def test_descarta_el_parrafo_estandar_de_wordpress(self):
        noticias = parsear_rss(self.contenido, NOMBRE_FUENTE)
        for noticia in noticias:
            self.assertNotIn("La entrada", noticia["texto"])
            self.assertNotIn("se publicó primero en", noticia["texto"])


class TestPipelineConFixtureRSS(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmpdir.name) / "test.db")
        self.redactor = RedactorMock()
        self.contenido = FIXTURE_PATH.read_bytes()

    def tearDown(self):
        self.db.close()
        self.tmpdir.cleanup()

    def test_noticia_departamental_de_fraile_pintado_queda_preparada_y_urgente(self):
        resultados = ejecutar_pipeline(self.db, ColectorRSSDePrueba(self.contenido), self.redactor)
        noticia_fraile, resultado = next(
            (n, r) for n, r in resultados if n.titulo_original == TITULO_FRAILE_PINTADO
        )
        self.assertEqual(resultado, "preparada")
        self.assertEqual(noticia_fraile.territorio, "departamental")
        self.assertTrue(noticia_fraile.urgente)

    def test_noticia_provincial_ajena_queda_preparada_sin_relevancia_local_ni_urgente(self):
        resultados = ejecutar_pipeline(self.db, ColectorRSSDePrueba(self.contenido), self.redactor)
        noticia_provincial, resultado = next(
            (n, r) for n, r in resultados if n.titulo_original == TITULO_PROVINCIAL
        )
        self.assertEqual(resultado, "preparada")
        self.assertEqual(noticia_provincial.territorio, "provincial")
        self.assertFalse(noticia_provincial.relevancia_local)
        self.assertFalse(noticia_provincial.urgente)

    def test_duplicado_no_se_almacena_dos_veces(self):
        resultados = ejecutar_pipeline(self.db, ColectorRSSDePrueba(self.contenido), self.redactor)
        self.assertEqual(resultados[3][1], "duplicado")
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

    @patch("motor_noticias.collectors.rss_jujuyaldia.urllib.request.urlopen")
    def test_usa_request_con_headers_en_lugar_de_url_cruda(self, urlopen_mock):
        urlopen_mock.return_value = self._respuesta_falsa(self.contenido_fixture)
        collector = JujuyAlDiaRSSCollector()

        noticias = collector.recolectar()

        urlopen_mock.assert_called_once()
        peticion_enviada = urlopen_mock.call_args.args[0]
        self.assertIsInstance(peticion_enviada, urllib.request.Request)
        self.assertEqual(peticion_enviada.full_url, collector.url)
        for clave, valor in HEADERS.items():
            self.assertEqual(peticion_enviada.get_header(clave.capitalize()), valor)
        self.assertEqual(len(noticias), 4)

    @patch("motor_noticias.collectors.rss_jujuyaldia.urllib.request.urlopen")
    def test_http_error_se_convierte_en_error_controlado(self, urlopen_mock):
        urlopen_mock.side_effect = urllib.error.HTTPError(
            url="https://www.jujuyaldia.com.ar/feed/",
            code=403,
            msg="Forbidden",
            hdrs=None,
            fp=None,
        )
        collector = JujuyAlDiaRSSCollector()

        with self.assertRaises(ErrorRecoleccionJujuyAlDia) as contexto:
            collector.recolectar()
        self.assertIn("403", str(contexto.exception))

    @patch("motor_noticias.collectors.rss_jujuyaldia.urllib.request.urlopen")
    def test_url_error_se_convierte_en_error_controlado(self, urlopen_mock):
        urlopen_mock.side_effect = urllib.error.URLError("nombre no resuelto")
        collector = JujuyAlDiaRSSCollector()

        with self.assertRaises(ErrorRecoleccionJujuyAlDia):
            collector.recolectar()


if __name__ == "__main__":
    unittest.main()
