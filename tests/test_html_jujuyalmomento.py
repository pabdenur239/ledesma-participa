import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import MagicMock, patch

from motor_noticias.collectors.html_jujuyalmomento import (
    HEADERS,
    ErrorRecoleccionJujuyAlMomento,
    JujuyAlMomentoHTMLCollector,
    parsear_listado,
)
from motor_noticias.db import Database
from motor_noticias.pipeline import ejecutar_pipeline
from motor_noticias.redaccion.mock import RedactorMock

FIXTURE_PATH = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "fixtures"
    / "jujuyalmomento_html_prueba.html"
)
NOMBRE_FUENTE = "Jujuy al Momento"
URL_BASE = "https://www.jujuyalmomento.com/"

TITULO_YUTO = (
    "Vecinos de Yuto reclaman por el estado de la ruta que conecta con "
    "Libertador General San Martín"
)
TITULO_CONCEJALES = "Concejales de Libertador General San Martín debaten el presupuesto municipal 2026"
TITULO_SAN_SALVADOR = "El gobierno provincial presentó un plan de obras hídricas en San Salvador de Jujuy"
TITULO_FRAILE_PINTADO = "Fraile Pintado tendrá una nueva plaza de juegos infantiles"
TITULO_ENCUESTA = "¿Cuál es tu equipo favorito?"


class ColectorHTMLDePrueba:
    """Envuelve el fixture HTML local. No realiza ninguna conexión de red."""

    def __init__(self, contenido):
        self.contenido = contenido

    def recolectar(self):
        return parsear_listado(self.contenido, URL_BASE, NOMBRE_FUENTE)


class TestParsearListado(unittest.TestCase):
    def setUp(self):
        self.contenido = FIXTURE_PATH.read_text(encoding="utf-8")

    def test_extrae_las_noticias_reales_incluido_el_duplicado(self):
        noticias = parsear_listado(self.contenido, URL_BASE, NOMBRE_FUENTE)
        titulos = [n["titulo"] for n in noticias]
        self.assertEqual(len(noticias), 5)  # incluye el duplicado, filtrado luego por el pipeline
        self.assertIn(TITULO_YUTO, titulos)
        self.assertIn(TITULO_CONCEJALES, titulos)
        self.assertIn(TITULO_SAN_SALVADOR, titulos)
        self.assertIn(TITULO_FRAILE_PINTADO, titulos)

    def test_extrae_titulo_resumen_url_y_fuente(self):
        noticias = parsear_listado(self.contenido, URL_BASE, NOMBRE_FUENTE)
        concejales = next(n for n in noticias if n["titulo"] == TITULO_CONCEJALES)
        self.assertEqual(
            concejales["texto"],
            "El Concejo Deliberante de Libertador General San Martín inició el debate "
            "por el presupuesto municipal 2026, con participación de distintos bloques "
            "políticos.",
        )
        self.assertEqual(
            concejales["url"],
            "https://www.jujuyalmomento.com/concejo-deliberante/concejales-libertador-debaten-presupuesto-municipal-2026-n205801",
        )
        self.assertEqual(concejales["fuente"], NOMBRE_FUENTE)

    def test_extrae_imagen_con_carga_diferida_via_longdesc(self):
        noticias = parsear_listado(self.contenido, URL_BASE, NOMBRE_FUENTE)
        yuto = next(n for n in noticias if n["titulo"] == TITULO_YUTO)
        # el <img> real usa src="...lazy.svg" (placeholder) y longdesc con la
        # URL real; debe tomar longdesc, nunca el placeholder de carga diferida.
        self.assertEqual(yuto["imagen_url"], "https://media.jujuyalmomento.com/p/aaa111/imagenes/ruta-yuto.jpg")
        self.assertNotIn("lazy.svg", yuto["imagen_url"])

    def test_extrae_imagen_con_src_directo(self):
        noticias = parsear_listado(self.contenido, URL_BASE, NOMBRE_FUENTE)
        concejales = next(n for n in noticias if n["titulo"] == TITULO_CONCEJALES)
        self.assertEqual(
            concejales["imagen_url"],
            "https://media.jujuyalmomento.com/p/bbb222/imagenes/concejo-libertador.jpg",
        )

    def test_imagen_vacia_cuando_no_existe(self):
        noticias = parsear_listado(self.contenido, URL_BASE, NOMBRE_FUENTE)
        fraile_pintado = next(n for n in noticias if n["titulo"] == TITULO_FRAILE_PINTADO)
        self.assertIsNone(fraile_pintado["imagen_url"])

    def test_no_extrae_fecha_porque_el_sitio_no_expone_ninguna_estable(self):
        # El listado real no tiene atributos datetime, <time>, ni datePublished
        # en el único JSON-LD (genérico, de tipo WebSite); no debe inferirse
        # ninguna fecha.
        noticias = parsear_listado(self.contenido, URL_BASE, NOMBRE_FUENTE)
        for noticia in noticias:
            self.assertEqual(noticia["fecha"], "")

    def test_no_captura_navegacion_footer_publicidad_ni_encuestas(self):
        noticias = parsear_listado(self.contenido, URL_BASE, NOMBRE_FUENTE)
        titulos = [n["titulo"] for n in noticias]
        for texto_no_deseado in ("Inicio", "Política", "Contacto", "Publicidad", TITULO_ENCUESTA):
            self.assertNotIn(texto_no_deseado, titulos)


class TestPipelineConFixtureHTML(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmpdir.name) / "test.db")
        self.redactor = RedactorMock()
        self.contenido = FIXTURE_PATH.read_text(encoding="utf-8")

    def tearDown(self):
        self.db.close()
        self.tmpdir.cleanup()

    def test_noticia_local_relevante_por_yuto(self):
        resultados = ejecutar_pipeline(self.db, ColectorHTMLDePrueba(self.contenido), self.redactor)
        noticia_yuto, resultado = next(
            (n, r) for n, r in resultados if n.titulo_original == TITULO_YUTO
        )
        self.assertEqual(resultado, "preparada")
        self.assertTrue(noticia_yuto.relevancia_local)
        self.assertTrue(noticia_yuto.tiene_imagen_original)
        self.assertEqual(
            noticia_yuto.imagen_publicacion_ruta,
            "https://media.jujuyalmomento.com/p/aaa111/imagenes/ruta-yuto.jpg",
        )

    def test_noticia_local_relevante_con_riesgo_institucional_por_concejales(self):
        resultados = ejecutar_pipeline(self.db, ColectorHTMLDePrueba(self.contenido), self.redactor)
        noticia_concejales, resultado = next(
            (n, r) for n, r in resultados if n.titulo_original == TITULO_CONCEJALES
        )
        self.assertEqual(resultado, "preparada")
        self.assertTrue(noticia_concejales.relevancia_local)
        # "Concejales" y "Concejo Deliberante" activan el control de riesgo
        # político/institucional existente, sin haberlo modificado.
        self.assertTrue(noticia_concejales.requiere_revision_especial)

    def test_noticia_provincial_ajena_queda_descartada(self):
        resultados = ejecutar_pipeline(self.db, ColectorHTMLDePrueba(self.contenido), self.redactor)
        noticia_san_salvador, resultado = next(
            (n, r) for n, r in resultados if n.titulo_original == TITULO_SAN_SALVADOR
        )
        self.assertEqual(resultado, "descartada")
        self.assertFalse(noticia_san_salvador.relevancia_local)

    def test_noticia_local_sin_imagen_usa_placa(self):
        resultados = ejecutar_pipeline(self.db, ColectorHTMLDePrueba(self.contenido), self.redactor)
        noticia_fraile_pintado, resultado = next(
            (n, r) for n, r in resultados if n.titulo_original == TITULO_FRAILE_PINTADO
        )
        self.assertEqual(resultado, "preparada")
        self.assertTrue(noticia_fraile_pintado.relevancia_local)
        self.assertFalse(noticia_fraile_pintado.tiene_imagen_original)

    def test_duplicado_no_se_almacena_dos_veces(self):
        resultados = ejecutar_pipeline(self.db, ColectorHTMLDePrueba(self.contenido), self.redactor)
        self.assertEqual(resultados[4][1], "duplicado")
        self.assertEqual(len(self.db.listar()), 4)

    def test_segunda_ejecucion_detecta_duplicados(self):
        ejecutar_pipeline(self.db, ColectorHTMLDePrueba(self.contenido), self.redactor)
        self.assertEqual(len(self.db.listar()), 4)

        segunda = ejecutar_pipeline(self.db, ColectorHTMLDePrueba(self.contenido), self.redactor)
        for _, resultado in segunda:
            self.assertEqual(resultado, "duplicado")
        self.assertEqual(len(self.db.listar()), 4)


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

    @patch("motor_noticias.collectors.html_jujuyalmomento.urllib.request.urlopen")
    def test_usa_request_con_headers_en_lugar_de_url_cruda(self, urlopen_mock):
        urlopen_mock.return_value = self._respuesta_falsa(self.contenido_fixture)
        collector = JujuyAlMomentoHTMLCollector()

        noticias = collector.recolectar()

        urlopen_mock.assert_called_once()
        peticion_enviada = urlopen_mock.call_args.args[0]
        self.assertIsInstance(peticion_enviada, urllib.request.Request)
        self.assertEqual(peticion_enviada.full_url, collector.url)
        for clave, valor in HEADERS.items():
            self.assertEqual(peticion_enviada.get_header(clave.capitalize()), valor)
        self.assertEqual(len(noticias), 5)

    @patch("motor_noticias.collectors.html_jujuyalmomento.urllib.request.urlopen")
    def test_http_error_se_convierte_en_error_controlado(self, urlopen_mock):
        urlopen_mock.side_effect = urllib.error.HTTPError(
            url=URL_BASE, code=403, msg="Forbidden", hdrs=None, fp=None
        )
        collector = JujuyAlMomentoHTMLCollector()

        with self.assertRaises(ErrorRecoleccionJujuyAlMomento) as contexto:
            collector.recolectar()
        self.assertIn("403", str(contexto.exception))

    @patch("motor_noticias.collectors.html_jujuyalmomento.urllib.request.urlopen")
    def test_url_error_se_convierte_en_error_controlado(self, urlopen_mock):
        urlopen_mock.side_effect = urllib.error.URLError("nombre no resuelto")
        collector = JujuyAlMomentoHTMLCollector()

        with self.assertRaises(ErrorRecoleccionJujuyAlMomento):
            collector.recolectar()


if __name__ == "__main__":
    unittest.main()
