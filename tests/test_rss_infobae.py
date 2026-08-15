import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import MagicMock, patch

from motor_noticias.collectors.rss_arc_nacional import parsear_rss_arc
from motor_noticias.collectors.rss_infobae import (
    HEADERS,
    ErrorRecoleccionInfobae,
    InfobaeRSSCollector,
)
from motor_noticias.db import Database
from motor_noticias.motor_editorial import generar_agenda
from motor_noticias.pipeline import ejecutar_pipeline
from motor_noticias.redaccion.mock import RedactorMock
from motor_noticias.verificacion_fuente import ResultadoVerificacionLocal

FIXTURE_PATH = Path(__file__).resolve().parent.parent / "data" / "fixtures" / "infobae_rss_prueba.xml"
NOMBRE_FUENTE = "Infobae"

TITULO_LOCAL = "Vecinos de Yuto reclaman por el estado de la ruta que conecta con Libertador General San Martín"
TITULO_PROVINCIAL = "La Legislatura de Jujuy declaró de interés provincial un festival cultural"
TITULO_NACIONAL = "El Gobierno nacional anunció cambios en la política de subsidios energéticos"
TITULO_SIN_CLASIFICAR = "Terremoto de magnitud 8,8 podría afectar a más de 14 millones de peruanos"
TITULO_SIN_IMAGEN = "Eclipse rural: del pastor galáctico con diploma de la NASA al cielo privilegiado de Porto"
TITULO_LOTERIA = "Hoy es el sorteo especial de la Lotería de Navidad anticipado"


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
        self.assertEqual(len(noticias), 7)  # incluye el duplicado; la lotería ya viene excluida
        self.assertIn(TITULO_LOCAL, titulos)
        self.assertIn(TITULO_PROVINCIAL, titulos)
        self.assertIn(TITULO_NACIONAL, titulos)

    def test_extrae_titulo_url_resumen_fecha_y_fuente(self):
        noticias = parsear_rss_arc(self.contenido, NOMBRE_FUENTE)
        local = next(n for n in noticias if n["titulo"] == TITULO_LOCAL)
        self.assertEqual(
            local["url"],
            "https://www.infobae.com/sociedad/2026/08/12/vecinos-de-yuto-reclaman-por-el-estado-de-la-ruta-que-conecta-con-libertador-general-san-martin/",
        )
        self.assertEqual(
            local["texto"],
            "Habitantes de Yuto, en el Departamento Ledesma, reclamaron obras urgentes en la ruta provincial.",
        )
        self.assertEqual(local["fecha"], "Wed, 12 Aug 2026 19:44:00 +0000")
        self.assertEqual(local["fuente"], NOMBRE_FUENTE)

    def test_extrae_imagen_desde_media_content(self):
        noticias = parsear_rss_arc(self.contenido, NOMBRE_FUENTE)
        local = next(n for n in noticias if n["titulo"] == TITULO_LOCAL)
        self.assertEqual(
            local["imagen_url"],
            "https://www.infobae.com/resizer/v2/AAAA111.jpg?auth=x&smart=true&width=1920&height=1080",
        )

    def test_item_sin_imagen_queda_vacio(self):
        # este item no tiene media:content ni <img> dentro de content:encoded
        noticias = parsear_rss_arc(self.contenido, NOMBRE_FUENTE)
        sin_imagen = next(n for n in noticias if n["titulo"] == TITULO_SIN_IMAGEN)
        self.assertIsNone(sin_imagen["imagen_url"])

    def test_resumen_desde_content_encoded_limpia_html_estilos_y_respeta_acentos(self):
        # description venía vacía (CDATA vacío) en este item real de Infobae:
        # el resumen sale de content:encoded, sin <style>, sin etiquetas, con
        # acentos bien decodificados desde las entidades HTML del feed real.
        noticias = parsear_rss_arc(self.contenido, NOMBRE_FUENTE)
        sin_imagen = next(n for n in noticias if n["titulo"] == TITULO_SIN_IMAGEN)
        self.assertNotIn("<", sin_imagen["texto"])
        self.assertNotIn("color:red", sin_imagen["texto"])
        self.assertIn("San Agustín del Pozo", sin_imagen["texto"])
        self.assertIn("experiencias únicas", sin_imagen["texto"])

    def test_infobae_no_trae_category_pero_igual_excluye_por_url(self):
        # el feed real de Infobae inspeccionado no trae <category> en ningún
        # item: la exclusión determinística se apoya en el segmento de URL.
        noticias = parsear_rss_arc(self.contenido, NOMBRE_FUENTE)
        titulos = [n["titulo"] for n in noticias]
        self.assertNotIn(TITULO_LOTERIA, titulos)
        # Infobae no trae <category>: el campo se expone igual (queda None)
        # para que la clasificación territorial nacional lo reciba de forma
        # homogénea con La Nación.
        for n in noticias:
            self.assertIn("categoria", n)
            self.assertIsNone(n["categoria"])


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
            "<link>https://www.infobae.com/sociedad/2026/08/12/nota-de-prueba-numero-{n}/</link>"
            "<description>Resumen de prueba con contenido suficiente para la nota numero {n}.</description>"
            "<pubDate>Wed, 12 Aug 2026 19:{n:02d}:00 +0000</pubDate></item>"
        )
        items_xml = "".join(item_tpl.format(n=i) for i in range(1, 41))
        noticias = parsear_rss_arc(self._feed_sintetico(items_xml), NOMBRE_FUENTE)
        self.assertEqual(len(noticias), 25)

    def test_deportes_no_domina_el_lote(self):
        deporte_tpl = (
            "<item><title><![CDATA[Partido de prueba numero {n}]]></title>"
            "<link>https://www.infobae.com/deportes/2026/08/12/partido-de-prueba-numero-{n}/</link>"
            "<description>Resumen deportivo de prueba con contenido suficiente numero {n}.</description>"
            "<pubDate>Wed, 12 Aug 2026 18:{n:02d}:00 +0000</pubDate></item>"
        )
        general_tpl = (
            "<item><title><![CDATA[Nota general numero {n}]]></title>"
            "<link>https://www.infobae.com/sociedad/2026/08/12/nota-general-numero-{n}/</link>"
            "<description>Resumen general de prueba con contenido suficiente numero {n}.</description>"
            "<pubDate>Wed, 12 Aug 2026 17:{n:02d}:00 +0000</pubDate></item>"
        )
        items_xml = "".join(deporte_tpl.format(n=i) for i in range(1, 31)) + "".join(
            general_tpl.format(n=i) for i in range(1, 11)
        )
        noticias = parsear_rss_arc(self._feed_sintetico(items_xml), NOMBRE_FUENTE)

        self.assertEqual(len(noticias), 25)
        deportivas = [n for n in noticias if "Partido de prueba" in n["titulo"]]
        generales = [n for n in noticias if "Nota general" in n["titulo"]]
        self.assertEqual(len(generales), 10)
        self.assertEqual(len(deportivas), 15)


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

    def test_noticia_internacional_sin_marca_nacional_queda_sin_clasificar(self):
        # Infobae es un feed internacional (secciones por país en la URL):
        # no se marca "nacional" solo por venir de esta fuente.
        resultados = ejecutar_pipeline(self.db, ColectorRSSDePrueba(self.contenido), self.redactor)
        noticia, resultado = next(
            (n, r) for n, r in resultados if n.titulo_original == TITULO_SIN_CLASIFICAR
        )
        self.assertEqual(resultado, "descartada")
        self.assertEqual(noticia.territorio, "sin_clasificar")

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

    @patch("motor_noticias.collectors.rss_infobae.urllib.request.urlopen")
    def test_usa_request_con_headers_en_lugar_de_url_cruda(self, urlopen_mock):
        urlopen_mock.return_value = self._respuesta_falsa(self.contenido_fixture)
        collector = InfobaeRSSCollector()

        noticias = collector.recolectar()

        urlopen_mock.assert_called_once()
        peticion_enviada = urlopen_mock.call_args.args[0]
        self.assertIsInstance(peticion_enviada, urllib.request.Request)
        self.assertEqual(peticion_enviada.full_url, collector.url)
        for clave, valor in HEADERS.items():
            self.assertEqual(peticion_enviada.get_header(clave.capitalize()), valor)
        self.assertEqual(len(noticias), 7)

    @patch("motor_noticias.collectors.rss_infobae.urllib.request.urlopen")
    def test_http_error_se_convierte_en_error_controlado(self, urlopen_mock):
        urlopen_mock.side_effect = urllib.error.HTTPError(
            url="https://www.infobae.com/arc/outboundfeeds/rss/",
            code=403,
            msg="Forbidden",
            hdrs=None,
            fp=None,
        )
        collector = InfobaeRSSCollector()

        with self.assertRaises(ErrorRecoleccionInfobae) as contexto:
            collector.recolectar()
        self.assertIn("403", str(contexto.exception))

    @patch("motor_noticias.collectors.rss_infobae.urllib.request.urlopen")
    def test_url_error_se_convierte_en_error_controlado(self, urlopen_mock):
        urlopen_mock.side_effect = urllib.error.URLError("nombre no resuelto")
        collector = InfobaeRSSCollector()

        with self.assertRaises(ErrorRecoleccionInfobae):
            collector.recolectar()


class TestIntegracionMotorContinuo(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmpdir.name) / "test.db")

    def tearDown(self):
        self.db.close()
        self.tmpdir.cleanup()

    def test_infobae_esta_registrada_en_las_fuentes_continuas(self):
        from motor_noticias.ciclo_continuo import FUENTES_CONTINUAS

        identificadores = [f[0] for f in FUENTES_CONTINUAS]
        self.assertIn("infobae", identificadores)

    @patch("motor_noticias.collectors.rss_infobae.urllib.request.urlopen")
    def test_ciclo_continuo_procesa_infobae_end_to_end(self, urlopen_mock):
        from motor_noticias.ciclo_continuo import ejecutar_ciclo

        respuesta = MagicMock()
        respuesta.read.return_value = FIXTURE_PATH.read_bytes()
        respuesta.__enter__.return_value = respuesta
        respuesta.__exit__.return_value = False
        urlopen_mock.return_value = respuesta

        fuentes_prueba = (("infobae", InfobaeRSSCollector, ErrorRecoleccionInfobae),)
        with patch("motor_noticias.ciclo_continuo.FUENTES_CONTINUAS", fuentes_prueba):
            ejecutar_ciclo(self.db, RedactorMock())

        salud = self.db.obtener_salud_fuente("infobae")
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
            verificar_impacto_provincial=lambda url: ResultadoVerificacionLocal(True, "prueba"),
        )

        territorios = [e.territorio for e in entradas]
        self.assertEqual(territorios[0], "local")
        self.assertIn("provincial", territorios)
        self.assertNotIn("nacional", territorios)


if __name__ == "__main__":
    unittest.main()
