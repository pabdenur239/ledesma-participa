import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import MagicMock, patch

from motor_noticias.collectors.html_infoyungas import (
    HEADERS,
    ErrorRecoleccionInfoYungas,
    InfoYungasHTMLCollector,
    parsear_listado,
)
from motor_noticias.db import Database
from motor_noticias.pipeline import ejecutar_pipeline
from motor_noticias.redaccion.mock import RedactorMock

FIXTURE_PATH = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "fixtures"
    / "infoyungas_html_prueba.html"
)
NOMBRE_FUENTE = "InfoYungas"
URL_BASE = "https://www.infoyungas.com/"

TITULO_HOSPITAL = "El municipio de Libertador General San Martín inauguró obras en el hospital"
TITULO_FRAILE_PINTADO = "Fraile Pintado: inauguraron un nuevo centro comunitario"
TITULO_NACIONAL = "El Gobierno nacional anunció cambios en la política económica"


class ColectorHTMLDePrueba:
    """Envuelve el fixture HTML local. No realiza ninguna conexión de red."""

    def __init__(self, contenido):
        self.contenido = contenido

    def recolectar(self):
        return parsear_listado(self.contenido, URL_BASE, NOMBRE_FUENTE)


class TestParsearListado(unittest.TestCase):
    def setUp(self):
        self.contenido = FIXTURE_PATH.read_text(encoding="utf-8")

    def test_extrae_las_tres_noticias_reales(self):
        noticias = parsear_listado(self.contenido, URL_BASE, NOMBRE_FUENTE)
        titulos = [n["titulo"] for n in noticias]
        self.assertEqual(len(noticias), 4)  # incluye el duplicado, filtrado luego por el pipeline
        self.assertIn(TITULO_HOSPITAL, titulos)
        self.assertIn(TITULO_FRAILE_PINTADO, titulos)
        self.assertIn(TITULO_NACIONAL, titulos)

    def test_extrae_titulo_resumen_url_y_fuente(self):
        noticias = parsear_listado(self.contenido, URL_BASE, NOMBRE_FUENTE)
        hospital = next(n for n in noticias if n["titulo"] == TITULO_HOSPITAL)
        self.assertEqual(
            hospital["texto"],
            "El intendente encabezó la inauguración de las nuevas salas del hospital, "
            "junto a vecinos del barrio.",
        )
        self.assertEqual(hospital["url"], "https://www.infoyungas.com/notas/obras-hospital-libertador")
        self.assertEqual(hospital["fuente"], NOMBRE_FUENTE)

    def test_extrae_imagen_cuando_existe(self):
        noticias = parsear_listado(self.contenido, URL_BASE, NOMBRE_FUENTE)
        hospital = next(n for n in noticias if n["titulo"] == TITULO_HOSPITAL)
        self.assertEqual(
            hospital["imagen_url"],
            "https://www.infoyungas.com/wp-content/uploads/2026/08/hospital.jpg",
        )

    def test_imagen_vacia_cuando_no_existe(self):
        noticias = parsear_listado(self.contenido, URL_BASE, NOMBRE_FUENTE)
        fraile_pintado = next(n for n in noticias if n["titulo"] == TITULO_FRAILE_PINTADO)
        self.assertIsNone(fraile_pintado["imagen_url"])

    def test_fecha_solo_cuando_es_explicita(self):
        noticias = parsear_listado(self.contenido, URL_BASE, NOMBRE_FUENTE)
        hospital = next(n for n in noticias if n["titulo"] == TITULO_HOSPITAL)
        fraile_pintado = next(n for n in noticias if n["titulo"] == TITULO_FRAILE_PINTADO)
        self.assertEqual(hospital["fecha"], "2026-08-10")
        self.assertEqual(fraile_pintado["fecha"], "")  # el fixture no incluye <time> para esta nota

    def test_no_captura_navegacion_footer_ni_publicidad(self):
        noticias = parsear_listado(self.contenido, URL_BASE, NOMBRE_FUENTE)
        titulos = [n["titulo"] for n in noticias]
        for texto_no_deseado in (
            "Inicio",
            "Política",
            "Deportes",
            "Contacto",
            "Publicidad",
            "ofertas de la semana",
        ):
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

    def test_noticia_local_relevante_queda_preparada_con_riesgo_institucional(self):
        resultados = ejecutar_pipeline(self.db, ColectorHTMLDePrueba(self.contenido), self.redactor)
        noticia_hospital, resultado = next(
            (n, r) for n, r in resultados if n.titulo_original == TITULO_HOSPITAL
        )
        self.assertEqual(resultado, "preparada")
        self.assertTrue(noticia_hospital.relevancia_local)
        # "municipio" e "intendente" activan el control de riesgo político/institucional
        self.assertTrue(noticia_hospital.requiere_revision_especial)

    def test_noticia_local_relevante_sin_imagen_queda_lista_para_placa_automatica(self):
        resultados = ejecutar_pipeline(self.db, ColectorHTMLDePrueba(self.contenido), self.redactor)
        noticia_fraile_pintado, resultado = next(
            (n, r) for n, r in resultados if n.titulo_original == TITULO_FRAILE_PINTADO
        )
        self.assertEqual(resultado, "preparada")
        self.assertTrue(noticia_fraile_pintado.relevancia_local)
        self.assertFalse(noticia_fraile_pintado.tiene_imagen_original)
        self.assertIsNone(noticia_fraile_pintado.imagen_publicacion_ruta)

    def test_noticia_ajena_queda_descartada(self):
        resultados = ejecutar_pipeline(self.db, ColectorHTMLDePrueba(self.contenido), self.redactor)
        noticia_nacional, resultado = next(
            (n, r) for n, r in resultados if n.titulo_original == TITULO_NACIONAL
        )
        self.assertEqual(resultado, "descartada")
        self.assertFalse(noticia_nacional.relevancia_local)

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

    @patch("motor_noticias.collectors.html_infoyungas.urllib.request.urlopen")
    def test_usa_request_con_headers_en_lugar_de_url_cruda(self, urlopen_mock):
        urlopen_mock.return_value = self._respuesta_falsa(self.contenido_fixture)
        collector = InfoYungasHTMLCollector()

        noticias = collector.recolectar()

        urlopen_mock.assert_called_once()
        peticion_enviada = urlopen_mock.call_args.args[0]
        self.assertIsInstance(peticion_enviada, urllib.request.Request)
        self.assertEqual(peticion_enviada.full_url, collector.url)
        for clave, valor in HEADERS.items():
            self.assertEqual(peticion_enviada.get_header(clave.capitalize()), valor)
        self.assertEqual(len(noticias), 4)

    @patch("motor_noticias.collectors.html_infoyungas.urllib.request.urlopen")
    def test_http_error_se_convierte_en_error_controlado(self, urlopen_mock):
        urlopen_mock.side_effect = urllib.error.HTTPError(
            url=URL_BASE, code=403, msg="Forbidden", hdrs=None, fp=None
        )
        collector = InfoYungasHTMLCollector()

        with self.assertRaises(ErrorRecoleccionInfoYungas) as contexto:
            collector.recolectar()
        self.assertIn("403", str(contexto.exception))

    @patch("motor_noticias.collectors.html_infoyungas.urllib.request.urlopen")
    def test_url_error_se_convierte_en_error_controlado(self, urlopen_mock):
        urlopen_mock.side_effect = urllib.error.URLError("nombre no resuelto")
        collector = InfoYungasHTMLCollector()

        with self.assertRaises(ErrorRecoleccionInfoYungas):
            collector.recolectar()


if __name__ == "__main__":
    unittest.main()
