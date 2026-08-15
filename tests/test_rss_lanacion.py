import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import MagicMock, patch

from motor_noticias.collectors.rss_arc_nacional import parsear_rss_arc
from motor_noticias.collectors.rss_lanacion import (
    HEADERS,
    ErrorRecoleccionLaNacion,
    LaNacionRSSCollector,
)
from motor_noticias.db import Database
from motor_noticias.motor_editorial import generar_agenda
from motor_noticias.pipeline import ejecutar_pipeline
from motor_noticias.redaccion.mock import RedactorMock
from motor_noticias.verificacion_fuente import ResultadoVerificacionLocal

FIXTURE_PATH = Path(__file__).resolve().parent.parent / "data" / "fixtures" / "lanacion_rss_prueba.xml"
NOMBRE_FUENTE = "La Nación"

TITULO_LOCAL = "El Concejo Deliberante de Libertador General San Martín aprobó el presupuesto 2026"
TITULO_PROVINCIAL = "La Legislatura de Jujuy debatirá un proyecto de ley sobre turismo provincial"
TITULO_NACIONAL = "Dólar hoy y dólar blue, EN VIVO: a cuánto cotiza el oficial este miércoles"
TITULO_SIN_IMAGEN = "Condenaron en Corrientes a un excombatiente por una estafa a jubilados"
TITULO_HOROSCOPO = "Horóscopo de hoy, miércoles 12 de agosto: qué le depara a cada signo"


class ColectorRSSDePrueba:
    """Envuelve el fixture XML local. No realiza ninguna conexión de red."""

    def __init__(self, contenido: bytes):
        self.contenido = contenido

    def recolectar(self):
        return parsear_rss_arc(self.contenido, NOMBRE_FUENTE)


class TestParsearRSS(unittest.TestCase):
    def setUp(self):
        self.contenido = FIXTURE_PATH.read_bytes()

    def test_extrae_varios_items(self):
        noticias = parsear_rss_arc(self.contenido, NOMBRE_FUENTE)
        titulos = [n["titulo"] for n in noticias]
        self.assertEqual(len(noticias), 6)  # incluye el duplicado; el horóscopo ya viene excluido
        self.assertIn(TITULO_LOCAL, titulos)
        self.assertIn(TITULO_PROVINCIAL, titulos)
        self.assertIn(TITULO_NACIONAL, titulos)

    def test_extrae_titulo_url_resumen_fecha_y_fuente(self):
        noticias = parsear_rss_arc(self.contenido, NOMBRE_FUENTE)
        local = next(n for n in noticias if n["titulo"] == TITULO_LOCAL)
        self.assertEqual(
            local["url"],
            "https://www.lanacion.com.ar/sociedad/el-concejo-deliberante-de-libertador-general-san-martin-aprobo-el-presupuesto-2026-nid12082026a/",
        )
        self.assertEqual(
            local["texto"],
            "Los concejales de Libertador General San Martín votaron por unanimidad "
            "el presupuesto municipal para el próximo año.",
        )
        self.assertEqual(local["fecha"], "Wed, 12 Aug 2026 19:43:44 +0000")
        self.assertEqual(local["fuente"], NOMBRE_FUENTE)

    def test_extrae_imagen_desde_media_content(self):
        noticias = parsear_rss_arc(self.contenido, NOMBRE_FUENTE)
        local = next(n for n in noticias if n["titulo"] == TITULO_LOCAL)
        self.assertEqual(
            local["imagen_url"],
            "https://resizer.glanacion.com/resizer/v2/AAAA111.jpg?auth=x&smart=true&width=2000&height=1333",
        )

    def test_item_sin_imagen_queda_vacio(self):
        noticias = parsear_rss_arc(self.contenido, NOMBRE_FUENTE)
        sin_imagen = next(n for n in noticias if n["titulo"] == TITULO_SIN_IMAGEN)
        self.assertIsNone(sin_imagen["imagen_url"])

    def test_resumen_desde_content_encoded_limpia_html_scripts_y_respeta_acentos(self):
        # description venía vacía en este item real: el resumen sale de
        # content:encoded, sin <script>, sin etiquetas, con acentos bien
        # decodificados desde las entidades HTML del feed real.
        noticias = parsear_rss_arc(self.contenido, NOMBRE_FUENTE)
        sin_imagen = next(n for n in noticias if n["titulo"] == TITULO_SIN_IMAGEN)
        self.assertNotIn("<", sin_imagen["texto"])
        self.assertNotIn("var x=1", sin_imagen["texto"])
        self.assertIn("tenía 68 años", sin_imagen["texto"])
        self.assertIn("captaba víctimas", sin_imagen["texto"])

    def test_categoria_se_usa_para_excluir_horoscopo_y_se_expone_para_territorio(self):
        noticias = parsear_rss_arc(self.contenido, NOMBRE_FUENTE)
        titulos = [n["titulo"] for n in noticias]
        self.assertNotIn(TITULO_HOROSCOPO, titulos)  # category "Horóscopo": exclusión determinística
        # La categoría real (cuando existe) se expone en el dict de la noticia
        # cruda: la usa la clasificación territorial nacional como evidencia
        # de sección argentina/internacional. No se persiste como campo nuevo
        # en el modelo de datos general (Noticia no tiene columna "categoria").
        con_categoria = [n for n in noticias if n.get("categoria")]
        self.assertTrue(con_categoria)


class TestLimiteYProporcionDeportes(unittest.TestCase):
    def _feed_sintetico(self, items_xml: str) -> bytes:
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<rss xmlns:content="http://purl.org/rss/1.0/modules/content/" version="2.0">'
            f"<channel><title>Prueba</title>{items_xml}</channel></rss>"
        ).encode("utf-8")

    def test_limite_maximo_25_items(self):
        item_tpl = (
            "<item><title><![CDATA[Nota de prueba numero {n}]]></title>"
            "<link>https://www.lanacion.com.ar/sociedad/nota-de-prueba-numero-{n}-nid{n}/</link>"
            "<description>Resumen de prueba con contenido suficiente para la nota numero {n}.</description>"
            "<pubDate>Wed, 12 Aug 2026 19:{n:02d}:00 +0000</pubDate>"
            "<category><![CDATA[Sociedad]]></category></item>"
        )
        items_xml = "".join(item_tpl.format(n=i) for i in range(1, 41))
        noticias = parsear_rss_arc(self._feed_sintetico(items_xml), NOMBRE_FUENTE)
        self.assertEqual(len(noticias), 25)

    def test_deportes_no_domina_el_lote(self):
        deporte_tpl = (
            "<item><title><![CDATA[Partido de prueba numero {n}]]></title>"
            "<link>https://www.lanacion.com.ar/deportes/partido-de-prueba-numero-{n}-nid{n}/</link>"
            "<description>Resumen deportivo de prueba con contenido suficiente numero {n}.</description>"
            "<pubDate>Wed, 12 Aug 2026 18:{n:02d}:00 +0000</pubDate>"
            "<category><![CDATA[Deportes]]></category></item>"
        )
        general_tpl = (
            "<item><title><![CDATA[Nota general numero {n}]]></title>"
            "<link>https://www.lanacion.com.ar/sociedad/nota-general-numero-{n}-nid{n}/</link>"
            "<description>Resumen general de prueba con contenido suficiente numero {n}.</description>"
            "<pubDate>Wed, 12 Aug 2026 17:{n:02d}:00 +0000</pubDate>"
            "<category><![CDATA[Sociedad]]></category></item>"
        )
        items_xml = "".join(deporte_tpl.format(n=i) for i in range(1, 31)) + "".join(
            general_tpl.format(n=i) for i in range(1, 11)
        )
        noticias = parsear_rss_arc(self._feed_sintetico(items_xml), NOMBRE_FUENTE)

        self.assertEqual(len(noticias), 25)
        deportivas = [n for n in noticias if "Partido de prueba" in n["titulo"]]
        generales = [n for n in noticias if "Nota general" in n["titulo"]]
        self.assertEqual(len(generales), 10)  # todo el contenido general entró
        self.assertEqual(len(deportivas), 15)  # deportes completó el resto, pero no dominó desde el vamos


class TestPipelineConFixtureRSS(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmpdir.name) / "test.db")
        self.redactor = RedactorMock()
        self.contenido = FIXTURE_PATH.read_bytes()

    def tearDown(self):
        self.db.close()
        self.tmpdir.cleanup()

    def test_noticia_local_queda_preparada_como_territorio_local(self):
        resultados = ejecutar_pipeline(self.db, ColectorRSSDePrueba(self.contenido), self.redactor)
        noticia, resultado = next((n, r) for n, r in resultados if n.titulo_original == TITULO_LOCAL)
        self.assertEqual(resultado, "preparada")
        self.assertEqual(noticia.territorio, "local")
        self.assertTrue(noticia.relevancia_local)

    def test_noticia_provincial_queda_preparada_sin_relevancia_local(self):
        resultados = ejecutar_pipeline(self.db, ColectorRSSDePrueba(self.contenido), self.redactor)
        noticia, resultado = next((n, r) for n, r in resultados if n.titulo_original == TITULO_PROVINCIAL)
        self.assertEqual(resultado, "preparada")
        self.assertEqual(noticia.territorio, "provincial")
        self.assertFalse(noticia.relevancia_local)

    def test_noticia_nacional_queda_preparada_sin_relevancia_local(self):
        resultados = ejecutar_pipeline(self.db, ColectorRSSDePrueba(self.contenido), self.redactor)
        noticia, resultado = next((n, r) for n, r in resultados if n.titulo_original == TITULO_NACIONAL)
        self.assertEqual(resultado, "preparada")
        self.assertEqual(noticia.territorio, "nacional")
        self.assertFalse(noticia.relevancia_local)

    def test_duplicado_no_se_almacena_dos_veces(self):
        resultados = ejecutar_pipeline(self.db, ColectorRSSDePrueba(self.contenido), self.redactor)
        self.assertEqual(resultados[-1][1], "duplicado")

    def test_segunda_ejecucion_detecta_duplicados(self):
        ejecutar_pipeline(self.db, ColectorRSSDePrueba(self.contenido), self.redactor)
        total_primera = len(self.db.listar())

        segunda = ejecutar_pipeline(self.db, ColectorRSSDePrueba(self.contenido), self.redactor)

        for _, resultado in segunda:
            self.assertEqual(resultado, "duplicado")
        self.assertEqual(len(self.db.listar()), total_primera)


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

    @patch("motor_noticias.collectors.rss_lanacion.urllib.request.urlopen")
    def test_usa_request_con_headers_en_lugar_de_url_cruda(self, urlopen_mock):
        urlopen_mock.return_value = self._respuesta_falsa(self.contenido_fixture)
        collector = LaNacionRSSCollector()

        noticias = collector.recolectar()

        urlopen_mock.assert_called_once()
        peticion_enviada = urlopen_mock.call_args.args[0]
        self.assertIsInstance(peticion_enviada, urllib.request.Request)
        self.assertEqual(peticion_enviada.full_url, collector.url)
        for clave, valor in HEADERS.items():
            self.assertEqual(peticion_enviada.get_header(clave.capitalize()), valor)
        self.assertEqual(len(noticias), 6)

    @patch("motor_noticias.collectors.rss_lanacion.urllib.request.urlopen")
    def test_http_error_se_convierte_en_error_controlado(self, urlopen_mock):
        urlopen_mock.side_effect = urllib.error.HTTPError(
            url="https://www.lanacion.com.ar/arc/outboundfeeds/rss/",
            code=403,
            msg="Forbidden",
            hdrs=None,
            fp=None,
        )
        collector = LaNacionRSSCollector()

        with self.assertRaises(ErrorRecoleccionLaNacion) as contexto:
            collector.recolectar()
        self.assertIn("403", str(contexto.exception))

    @patch("motor_noticias.collectors.rss_lanacion.urllib.request.urlopen")
    def test_url_error_se_convierte_en_error_controlado(self, urlopen_mock):
        urlopen_mock.side_effect = urllib.error.URLError("nombre no resuelto")
        collector = LaNacionRSSCollector()

        with self.assertRaises(ErrorRecoleccionLaNacion):
            collector.recolectar()


class TestIntegracionMotorContinuo(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmpdir.name) / "test.db")

    def tearDown(self):
        self.db.close()
        self.tmpdir.cleanup()

    def test_la_nacion_esta_registrada_en_las_fuentes_continuas(self):
        from motor_noticias.ciclo_continuo import FUENTES_CONTINUAS

        identificadores = [f[0] for f in FUENTES_CONTINUAS]
        self.assertIn("la-nacion", identificadores)

    @patch("motor_noticias.collectors.rss_lanacion.urllib.request.urlopen")
    def test_ciclo_continuo_procesa_la_nacion_end_to_end(self, urlopen_mock):
        from motor_noticias.ciclo_continuo import ejecutar_ciclo

        respuesta = MagicMock()
        respuesta.read.return_value = FIXTURE_PATH.read_bytes()
        respuesta.__enter__.return_value = respuesta
        respuesta.__exit__.return_value = False
        urlopen_mock.return_value = respuesta

        fuentes_prueba = (("la-nacion", LaNacionRSSCollector, ErrorRecoleccionLaNacion),)
        with patch("motor_noticias.ciclo_continuo.FUENTES_CONTINUAS", fuentes_prueba):
            ejecutar_ciclo(self.db, RedactorMock())

        salud = self.db.obtener_salud_fuente("la-nacion")
        self.assertEqual(salud["ultimo_resultado"], "ok")
        self.assertGreater(salud["noticias_nuevas"], 0)


class TestIntegracionMotorEditorial(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmpdir.name) / "test.db")
        self.redactor = RedactorMock()
        self.contenido = FIXTURE_PATH.read_bytes()

    def tearDown(self):
        self.db.close()
        self.tmpdir.cleanup()

    def test_provincial_verificado_se_usa_pero_nacional_nunca_se_elige(self):
        ejecutar_pipeline(self.db, ColectorRSSDePrueba(self.contenido), self.redactor)

        entradas = generar_agenda(
            self.db, fecha="2026-08-12", horarios=("08:00", "10:30", "13:00"),
            verificar_impacto_provincial=lambda titulo, url: ResultadoVerificacionLocal(True, "prueba"),
        )

        territorios = [e.territorio for e in entradas]
        # local y provincial (verificado) se usan; nacional nunca se elige.
        self.assertEqual(territorios[0], "local")
        self.assertIn("provincial", territorios)
        self.assertNotIn("nacional", territorios)


if __name__ == "__main__":
    unittest.main()
