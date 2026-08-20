import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import MagicMock, patch

from motor_noticias.collectors.rss_jujuygrafico import (
    ErrorRecoleccionJujuyGrafico,
    HEADERS,
    JujuyGraficoRSSCollector,
    parsear_rss,
)
from motor_noticias.db import Database
from motor_noticias.pipeline import ejecutar_pipeline
from motor_noticias.redaccion.mock import RedactorMock

FIXTURE_PATH = Path(__file__).resolve().parent.parent / "data" / "fixtures" / "jujuygrafico_rss_prueba.xml"
NOMBRE_FUENTE = "Jujuy Gráfico"

TITULO_HOSPITAL = "El Ramal celebra la ampliación del hospital de Libertador General San Martín"
TITULO_TURISMO = "El gobierno de Jujuy presentó el balance turístico de la temporada"


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
        self.assertEqual(len(noticias), 3)  # incluye el duplicado, filtrado luego por el pipeline
        self.assertIn(TITULO_HOSPITAL, titulos)
        self.assertIn(TITULO_TURISMO, titulos)

    def test_extrae_titulo_resumen_url_fecha_y_fuente(self):
        noticias = parsear_rss(self.contenido, NOMBRE_FUENTE)
        hospital = next(n for n in noticias if n["titulo"] == TITULO_HOSPITAL)
        self.assertEqual(
            hospital["texto"],
            "Las autoridades sanitarias anunciaron la ampliación del nosocomio de Libertador "
            "General San Martín, en el Ramal jujeño.",
        )
        self.assertEqual(
            hospital["url"], "https://jujuygrafico.com.ar/2026/08/17/hospital-libertador-ampliacion/"
        )
        self.assertEqual(hospital["fecha"], "Mon, 17 Aug 2026 12:00:00 +0000")
        self.assertEqual(hospital["fuente"], NOMBRE_FUENTE)

    def test_extrae_imagen_embebida_en_la_descripcion(self):
        noticias = parsear_rss(self.contenido, NOMBRE_FUENTE)
        hospital = next(n for n in noticias if n["titulo"] == TITULO_HOSPITAL)
        self.assertEqual(
            hospital["imagen_url"],
            "https://jujuygrafico.com.ar/wp-content/uploads/2026/08/hospital.jpg",
        )
        self.assertNotIn("<img", hospital["texto"])

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

    def test_noticia_local_de_libertador_queda_preparada_y_urgente(self):
        resultados = ejecutar_pipeline(self.db, ColectorRSSDePrueba(self.contenido), self.redactor)
        noticia_hospital, resultado = next(
            (n, r) for n, r in resultados if n.titulo_original == TITULO_HOSPITAL
        )
        self.assertEqual(resultado, "preparada")
        self.assertEqual(noticia_hospital.territorio, "local")
        self.assertTrue(noticia_hospital.urgente)

    def test_noticia_provincial_ajena_queda_preparada_sin_relevancia_local_ni_urgente(self):
        resultados = ejecutar_pipeline(self.db, ColectorRSSDePrueba(self.contenido), self.redactor)
        noticia_turismo, resultado = next(
            (n, r) for n, r in resultados if n.titulo_original == TITULO_TURISMO
        )
        self.assertEqual(resultado, "preparada")
        self.assertEqual(noticia_turismo.territorio, "provincial")
        self.assertFalse(noticia_turismo.relevancia_local)
        self.assertFalse(noticia_turismo.urgente)

    def test_duplicado_no_se_almacena_dos_veces(self):
        resultados = ejecutar_pipeline(self.db, ColectorRSSDePrueba(self.contenido), self.redactor)
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

    @patch("motor_noticias.collectors.rss_jujuygrafico.urllib.request.urlopen")
    def test_usa_request_con_headers_en_lugar_de_url_cruda(self, urlopen_mock):
        urlopen_mock.return_value = self._respuesta_falsa(self.contenido_fixture)
        collector = JujuyGraficoRSSCollector()

        noticias = collector.recolectar()

        urlopen_mock.assert_called_once()
        peticion_enviada = urlopen_mock.call_args.args[0]
        self.assertIsInstance(peticion_enviada, urllib.request.Request)
        self.assertEqual(peticion_enviada.full_url, collector.url)
        for clave, valor in HEADERS.items():
            self.assertEqual(peticion_enviada.get_header(clave.capitalize()), valor)
        self.assertEqual(len(noticias), 3)

    @patch("motor_noticias.collectors.rss_jujuygrafico.urllib.request.urlopen")
    def test_http_error_se_convierte_en_error_controlado(self, urlopen_mock):
        urlopen_mock.side_effect = urllib.error.HTTPError(
            url="https://jujuygrafico.com.ar/feed/",
            code=403,
            msg="Forbidden",
            hdrs=None,
            fp=None,
        )
        collector = JujuyGraficoRSSCollector()

        with self.assertRaises(ErrorRecoleccionJujuyGrafico) as contexto:
            collector.recolectar()
        self.assertIn("403", str(contexto.exception))

    @patch("motor_noticias.collectors.rss_jujuygrafico.urllib.request.urlopen")
    def test_url_error_se_convierte_en_error_controlado(self, urlopen_mock):
        urlopen_mock.side_effect = urllib.error.URLError("nombre no resuelto")
        collector = JujuyGraficoRSSCollector()

        with self.assertRaises(ErrorRecoleccionJujuyGrafico):
            collector.recolectar()


if __name__ == "__main__":
    unittest.main()
