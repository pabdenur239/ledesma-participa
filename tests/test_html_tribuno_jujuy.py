import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import MagicMock, patch

from motor_noticias.collectors.html_tribuno_jujuy import (
    HEADERS,
    ErrorRecoleccionTribunoJujuy,
    TribunoJujuyHTMLCollector,
    parsear_listado,
)
from motor_noticias.db import Database
from motor_noticias.pipeline import ejecutar_pipeline
from motor_noticias.redaccion.mock import RedactorMock

FIXTURE_PATH = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "fixtures"
    / "tribuno_jujuy_html_prueba.html"
)
NOMBRE_FUENTE = "El Tribuno de Jujuy"
URL_BASE = "https://eltribunodejujuy.com/"

TITULO_CONCEJO = "El Concejo Deliberante de Libertador aprobó la ordenanza de arbolado urbano"
TITULO_CALILEGUA = "Calilegua inauguró un nuevo centro cultural vecinal"
TITULO_PROVINCIAL = "El Gobierno provincial presentó el balance turístico de invierno"


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
        self.assertEqual(len(noticias), 4)  # incluye el duplicado, filtrado luego por el pipeline
        self.assertIn(TITULO_CONCEJO, titulos)
        self.assertIn(TITULO_CALILEGUA, titulos)
        self.assertIn(TITULO_PROVINCIAL, titulos)

    def test_extrae_titulo_resumen_url_y_fuente(self):
        noticias = parsear_listado(self.contenido, URL_BASE, NOMBRE_FUENTE)
        concejo = next(n for n in noticias if n["titulo"] == TITULO_CONCEJO)
        self.assertEqual(
            concejo["texto"],
            "Los concejales de Libertador General San Martín votaron por unanimidad "
            "la nueva ordenanza que regula la plantación y el cuidado del arbolado "
            "en la ciudad.",
        )
        self.assertEqual(
            concejo["url"],
            "https://eltribunodejujuy.com/informacion-general/2026-8-12-9-30-0-concejo-deliberante-libertador-aprobo-ordenanza-arbolado-urbano",
        )
        self.assertEqual(concejo["fuente"], NOMBRE_FUENTE)

    def test_extrae_imagen(self):
        noticias = parsear_listado(self.contenido, URL_BASE, NOMBRE_FUENTE)
        calilegua = next(n for n in noticias if n["titulo"] == TITULO_CALILEGUA)
        self.assertEqual(
            calilegua["imagen_url"],
            "https://uscdn.eltribunodejujuy.com/082026/2222222222.webp?cw=420&ch=236",
        )

    def test_imagen_vacia_cuando_la_variante_de_tarjeta_no_la_incluye(self):
        noticias = parsear_listado(self.contenido, URL_BASE, NOMBRE_FUENTE)
        provincial = next(n for n in noticias if n["titulo"] == TITULO_PROVINCIAL)
        self.assertIsNone(provincial["imagen_url"])

    def test_extrae_fecha_explicita_desde_el_permalink(self):
        # El sitio no expone un campo de fecha aparte, pero el permalink de
        # cada nota incluye la fecha y hora de publicación de forma
        # explícita y estable (p. ej. /seccion/2026-8-12-9-30-0-slug).
        noticias = parsear_listado(self.contenido, URL_BASE, NOMBRE_FUENTE)
        concejo = next(n for n in noticias if n["titulo"] == TITULO_CONCEJO)
        self.assertEqual(concejo["fecha"], "2026-08-12T09:30:00")
        calilegua = next(n for n in noticias if n["titulo"] == TITULO_CALILEGUA)
        self.assertEqual(calilegua["fecha"], "2026-08-12T08:15:00")

    def test_no_captura_navegacion_footer_ni_publicidad(self):
        noticias = parsear_listado(self.contenido, URL_BASE, NOMBRE_FUENTE)
        titulos = [n["titulo"] for n in noticias]
        for texto_no_deseado in ("Inicio", "Política", "Contacto", "Publicidad"):
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

    def test_noticia_local_relevante_con_riesgo_institucional_por_concejo(self):
        resultados = ejecutar_pipeline(self.db, ColectorHTMLDePrueba(self.contenido), self.redactor)
        noticia_concejo, resultado = next(
            (n, r) for n, r in resultados if n.titulo_original == TITULO_CONCEJO
        )
        self.assertEqual(resultado, "preparada")
        self.assertTrue(noticia_concejo.relevancia_local)
        self.assertTrue(noticia_concejo.tiene_imagen_original)
        self.assertEqual(
            noticia_concejo.imagen_publicacion_ruta,
            "https://uscdn.eltribunodejujuy.com/082026/1111111111.webp?cw=420&ch=236",
        )
        # "Concejo Deliberante" activa el control de riesgo político/
        # institucional existente, sin haberlo modificado.
        self.assertTrue(noticia_concejo.requiere_revision_especial)

    def test_noticia_local_relevante_por_calilegua_sin_riesgo(self):
        resultados = ejecutar_pipeline(self.db, ColectorHTMLDePrueba(self.contenido), self.redactor)
        noticia_calilegua, resultado = next(
            (n, r) for n, r in resultados if n.titulo_original == TITULO_CALILEGUA
        )
        self.assertEqual(resultado, "preparada")
        self.assertTrue(noticia_calilegua.relevancia_local)
        self.assertFalse(noticia_calilegua.requiere_revision_especial)

    def test_noticia_provincial_ajena_queda_descartada(self):
        resultados = ejecutar_pipeline(self.db, ColectorHTMLDePrueba(self.contenido), self.redactor)
        noticia_provincial, resultado = next(
            (n, r) for n, r in resultados if n.titulo_original == TITULO_PROVINCIAL
        )
        self.assertEqual(resultado, "descartada")
        self.assertFalse(noticia_provincial.relevancia_local)

    def test_noticia_sin_imagen_usa_placa(self):
        resultados = ejecutar_pipeline(self.db, ColectorHTMLDePrueba(self.contenido), self.redactor)
        noticia_provincial, _ = next(
            (n, r) for n, r in resultados if n.titulo_original == TITULO_PROVINCIAL
        )
        self.assertFalse(noticia_provincial.tiene_imagen_original)

    def test_duplicado_no_se_almacena_dos_veces(self):
        resultados = ejecutar_pipeline(self.db, ColectorHTMLDePrueba(self.contenido), self.redactor)
        self.assertEqual(resultados[3][1], "duplicado")
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

    @patch("motor_noticias.collectors.html_tribuno_jujuy.urllib.request.urlopen")
    def test_usa_request_con_headers_en_lugar_de_url_cruda(self, urlopen_mock):
        urlopen_mock.return_value = self._respuesta_falsa(self.contenido_fixture)
        collector = TribunoJujuyHTMLCollector()

        noticias = collector.recolectar()

        urlopen_mock.assert_called_once()
        peticion_enviada = urlopen_mock.call_args.args[0]
        self.assertIsInstance(peticion_enviada, urllib.request.Request)
        self.assertEqual(peticion_enviada.full_url, collector.url)
        for clave, valor in HEADERS.items():
            self.assertEqual(peticion_enviada.get_header(clave.capitalize()), valor)
        self.assertEqual(len(noticias), 4)

    @patch("motor_noticias.collectors.html_tribuno_jujuy.urllib.request.urlopen")
    def test_http_error_se_convierte_en_error_controlado(self, urlopen_mock):
        urlopen_mock.side_effect = urllib.error.HTTPError(
            url=URL_BASE, code=403, msg="Forbidden", hdrs=None, fp=None
        )
        collector = TribunoJujuyHTMLCollector()

        with self.assertRaises(ErrorRecoleccionTribunoJujuy) as contexto:
            collector.recolectar()
        self.assertIn("403", str(contexto.exception))

    @patch("motor_noticias.collectors.html_tribuno_jujuy.urllib.request.urlopen")
    def test_url_error_se_convierte_en_error_controlado(self, urlopen_mock):
        urlopen_mock.side_effect = urllib.error.URLError("nombre no resuelto")
        collector = TribunoJujuyHTMLCollector()

        with self.assertRaises(ErrorRecoleccionTribunoJujuy):
            collector.recolectar()


if __name__ == "__main__":
    unittest.main()
