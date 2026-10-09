"""Cobertura web/app (9/10/2026): volumen ~45, prioridad local sin bloqueo
por cupo, recuperación local 48 h, internacional limitado y solo para el
portal, alertas de fuentes, tolerancia a fallos de Ollama y lectura RSS de
InfoYungas, Jujuy al Momento y El Tribuno con respaldo HTML. Redes sin
cambios: lo nuevo nunca entra a los circuitos de Meta."""
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from motor_noticias import portal
from motor_noticias.alertas import calcular_alertas
from motor_noticias.ciclo_continuo import _procesar_fuente
from motor_noticias.collectors._rss_generico import ErrorRecoleccionRSSGenerico
from motor_noticias.collectors.rss_regionales import (
    InfoYungasRSSCollector,
    JujuyAlMomentoRSSCollector,
    TribunoJujuyRSSCollector,
    parsear_rss_regional,
)
from motor_noticias.db import Database
from motor_noticias.models import Estado, Noticia
from motor_noticias.motor_editorial import ZONA_JUJUY
from motor_noticias.pipeline import MARCA_SIN_REDACCION, ejecutar_pipeline
from motor_noticias.redaccion.base import Redactor
from motor_noticias.redaccion.mock import RedactorMock
from motor_noticias.redaccion.ollama import ErrorRedaccionOllama

FIXTURES = Path(__file__).resolve().parent.parent / "data" / "fixtures"
AHORA = datetime(2026, 10, 9, 10, 0, tzinfo=ZONA_JUJUY)

LUGAR = {
    "local": "en Libertador General San Martín",
    "departamental": "en Calilegua",
    "provincial": "en San Salvador de Jujuy",
    "nacional": "en Argentina",
}
TEMAS = [
    "inflación", "jubilaciones", "rutas", "escuelas", "hospitales", "elecciones", "lluvias", "precios", "fútbol",
    "teatro", "salarios", "tránsito", "vacunas", "turismo", "becas", "puentes", "colectivos", "museos", "energía",
    "acueductos", "industria", "comercio", "empleo", "créditos", "viviendas", "parques", "música", "ciencia",
    "minería", "agricultura", "bibliotecas", "ferrocarriles", "aeropuertos", "cooperativas", "bomberos", "ajedrez",
    "natación", "ciclismo", "danza", "cine", "pintura", "astronomía", "robótica", "apicultura", "ganadería",
    "vendimia", "carnaval", "artesanías", "orquestas", "maratones", "olimpíadas", "telecomunicaciones", "satélites",
]


def _guardar(db, n, titulo, territorio, horas=1, estado=Estado.PREPARADA.value, **extra):
    momento = (AHORA - timedelta(hours=horas)).astimezone(timezone.utc).isoformat()
    texto = f"{titulo}. Texto con información suficiente y verificable para la nota número {n}."
    datos = dict(
        id=None, titulo_original=titulo, texto_original=texto, url_fuente=f"https://medio.test/nota-{n}",
        url_normalizada=f"https://medio.test/nota-{n}", nombre_fuente="Medio de prueba", fecha_fuente="",
        fecha_recoleccion=momento, estado=estado, hash_contenido=f"h{n}", titulo_preparado=titulo,
        texto_preparado=texto, territorio=territorio,
    )
    datos.update(extra)
    return db.guardar(Noticia(**datos))


def _seleccion(db, fecha=None):
    fecha = fecha or AHORA.date().isoformat()
    return db.portal_seleccion_por_fecha([fecha]).get(fecha, [])


class _BaseDB(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "t.db")

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()


class TestSeleccionPortal(_BaseDB):
    def _llenar(self, territorio, cantidad, desde=0, horas=1):
        for i in range(cantidad):
            # Temas distintos por territorio: el mismo tema en dos territorios
            # sería el "mismo hecho" para el control de repetición.
            j = i + desde // 100 * 18
            titulo = f"{TEMAS[j % len(TEMAS)].capitalize()} y {TEMAS[(j + 9) % len(TEMAS)]} {LUGAR[territorio]}"
            _guardar(self.db, desde + i, titulo, territorio, horas=horas)

    def test_local_entra_aunque_el_cupo_general_este_avanzado(self):
        self._llenar("provincial", 25, desde=0)
        self._llenar("nacional", 25, desde=100)
        portal.completar_seleccion(self.db, AHORA)
        antes = len(_seleccion(self.db))
        _guardar(self.db, 500, "Corte programado de energía en el barrio Jardín de Libertador General San Martín", "local")
        _guardar(self.db, 501, "Calilegua abre la inscripción a talleres de oficios", "departamental")
        portal.completar_seleccion(self.db, AHORA)
        seleccion = _seleccion(self.db)
        titulos = {self.db.obtener(i)["titulo_original"] for i in seleccion}
        self.assertIn("Corte programado de energía en el barrio Jardín de Libertador General San Martín", titulos)
        self.assertIn("Calilegua abre la inscripción a talleres de oficios", titulos)
        self.assertEqual(len(seleccion), antes + 2)

    def test_nacional_no_monopoliza_el_dia(self):
        self._llenar("nacional", 45, desde=0)
        portal.completar_seleccion(self.db, AHORA.replace(hour=23))
        nacionales = len(_seleccion(self.db))
        self.assertLessEqual(nacionales, portal.TOPES_POR_TERRITORIO["nacional"])
        self.assertGreater(nacionales, 0)

    def test_volumen_total_hasta_45_sin_rellenar(self):
        self._llenar("provincial", 18, desde=0)
        self._llenar("nacional", 18, desde=100)
        self._llenar("local", 18, desde=200)
        portal.completar_seleccion(self.db, AHORA.replace(hour=23))
        total = len(_seleccion(self.db))
        # 18 locales (todas) + 15 provinciales (tope) + 10 nacionales (tope).
        self.assertEqual(total, 18 + portal.TOPES_POR_TERRITORIO["provincial"] + portal.TOPES_POR_TERRITORIO["nacional"])

    def test_internacional_entra_dentro_de_su_maximo(self):
        paises = ["Francia", "Brasil", "Chile", "Japón", "Canadá", "México", "Italia", "Perú"]
        for i, pais in enumerate(paises):
            _guardar(self.db, i, f"{pais}: {TEMAS[i]} y {TEMAS[i + 25]}", "internacional",
                     estado=Estado.SOLO_PORTAL.value, categoria_tematica="internacional")
        portal.completar_seleccion(self.db, AHORA.replace(hour=23))
        self.assertEqual(len(_seleccion(self.db)), portal.TOPES_POR_TERRITORIO["internacional"])

    def test_recuperacion_local_48h(self):
        # Hace 40 h (anteayer): entra. Hace 60 h: vencida. Urgente vieja: superada.
        _guardar(self.db, 1, "Vecinos de Libertador General San Martín inauguran una huerta comunitaria", "local", horas=40)
        _guardar(self.db, 2, "Feria de emprendedores en Libertador General San Martín", "local", horas=60)
        _guardar(self.db, 3, "Corte total de agua en Libertador General San Martín", "local", horas=40, urgente=True)
        _guardar(self.db, 4, "Novedades sobre turismo en Argentina", "nacional", horas=40)
        portal.completar_seleccion(self.db, AHORA)
        anteayer = (AHORA - timedelta(hours=40)).date().isoformat()
        titulos = {self.db.obtener(i)["titulo_original"] for i in _seleccion(self.db, anteayer)}
        self.assertEqual(titulos, {"Vecinos de Libertador General San Martín inauguran una huerta comunitaria"})

    def test_recuperacion_no_trae_un_hecho_ya_publicado(self):
        _guardar(self.db, 1, "Inauguran la nueva plaza del barrio Talleres en Libertador General San Martín", "local",
                 horas=5, estado=Estado.PUBLICADA.value)
        _guardar(self.db, 2, "Inauguraron la nueva plaza del barrio Talleres en Libertador General San Martín", "local",
                 horas=40)
        portal.completar_seleccion(self.db, AHORA)
        anteayer = (AHORA - timedelta(hours=40)).date().isoformat()
        self.assertEqual(_seleccion(self.db, anteayer), [])

    def test_duplicados_no_reaparecen_en_corridas_siguientes(self):
        _guardar(self.db, 1, "Vecinos de Libertador General San Martín inauguran una huerta comunitaria", "local", horas=40)
        portal.completar_seleccion(self.db, AHORA)
        segunda = portal.completar_seleccion(self.db, AHORA + timedelta(minutes=15))
        self.assertEqual(sum(segunda.values()), 0)
        filas = self.db.conn.execute("SELECT COUNT(*) FROM portal_seleccion").fetchone()[0]
        self.assertEqual(filas, 1)

    def test_local_sensible_aprobada_por_una_persona_entra(self):
        _guardar(self.db, 1, "Falleció un reconocido docente de Libertador General San Martín", "local",
                 requiere_revision_especial=True, categoria_riesgo="muertes", revision_estado="aprobada")
        _guardar(self.db, 2, "Sepelio de un vecino de Libertador General San Martín", "local",
                 requiere_revision_especial=True, categoria_riesgo="muertes")
        _guardar(self.db, 3, "Un niño de Libertador General San Martín ganó un concurso", "local",
                 requiere_revision_especial=True, categoria_riesgo="menores_identificables", revision_estado="aprobada")
        _guardar(self.db, 4, "Detuvieron a un hombre en Libertador General San Martín", "local",
                 requiere_revision_especial=True, categoria_riesgo="judicial", revision_estado="aprobada",
                 revision_automatica=True)
        portal.completar_seleccion(self.db, AHORA)
        titulos = {self.db.obtener(i)["titulo_original"] for i in _seleccion(self.db)}
        self.assertEqual(titulos, {"Falleció un reconocido docente de Libertador General San Martín"})


class TestRedesSinCambios(_BaseDB):
    def test_solo_portal_nunca_es_candidata_de_meta(self):
        _guardar(self.db, 1, "El gobierno de Francia anunció cambios en jubilaciones", "internacional",
                 estado=Estado.SOLO_PORTAL.value, categoria_tematica="internacional", urgente=True)
        limite = (AHORA - timedelta(days=2)).astimezone(timezone.utc).isoformat()
        self.assertEqual(self.db.candidatos_editoriales(set(), limite), [])
        self.assertEqual(self.db.candidatos_urgentes(set(), limite), [])
        self.assertEqual(self.db.listar_preparadas(), [])

    def test_portal_no_toca_la_agenda_de_redes(self):
        _guardar(self.db, 1, "Novedades sobre turismo en San Salvador de Jujuy", "provincial")
        portal.completar_seleccion(self.db, AHORA)
        self.assertEqual(self.db.listar_agenda(AHORA.date().isoformat()), [])

    def test_internacional_relevante_queda_solo_portal_y_no_urgente(self):
        class _Collector:
            def recolectar(self):
                return [
                    {"titulo": "Elecciones en Brasil: Lula y Bolsonaro van a segunda vuelta",
                     "texto": "El balotaje se realizará el 30 de octubre según la autoridad electoral brasileña.",
                     "url": "https://int.test/1", "fuente": "BBC Mundo", "categoria_tematica": "internacional"},
                    {"titulo": "Un museo de Londres exhibe una colección de relojes antiguos",
                     "texto": "La muestra reúne piezas de varios siglos en una sala renovada del museo.",
                     "url": "https://int.test/2", "fuente": "BBC Mundo", "categoria_tematica": "internacional"},
                ]

        resultados = ejecutar_pipeline(self.db, _Collector(), RedactorMock())
        estados = {n.titulo_original: (n.estado, n.urgente) for n, _ in resultados}
        self.assertEqual(estados["Elecciones en Brasil: Lula y Bolsonaro van a segunda vuelta"], ("solo_portal", False))
        self.assertEqual(estados["Un museo de Londres exhibe una colección de relojes antiguos"][0], "descartada")


class _CollectorLocal:
    def recolectar(self):
        return [
            {"titulo": f"Obras de cordón cuneta número {i} en Libertador General San Martín",
             "texto": f"La municipalidad de Libertador General San Martín avanza con la obra {i} en el barrio Norte.",
             "url": f"https://local.test/{i}", "fuente": "Medio local"}
            for i in range(2)
        ]


class _RedactorCaido(Redactor):
    def redactar(self, noticia):
        raise ErrorRedaccionOllama("Ollama no respondió dentro del timeout")


class TestOllamaNoTumbaLaFuente(_BaseDB):
    def test_fuente_sigue_con_texto_original(self):
        resultado = _procesar_fuente(self.db, "local-prueba", _CollectorLocal, RuntimeError, _RedactorCaido())
        self.assertEqual(resultado.resultado, "ok")
        self.assertEqual(resultado.elementos_obtenidos, 2)
        preparadas = self.db.listar_preparadas()
        self.assertEqual(len(preparadas), 2)
        for n in preparadas:
            self.assertEqual(n["texto_preparado"], n["texto_original"])
            self.assertTrue(n["observacion_interna"].startswith(MARCA_SIN_REDACCION))


class TestAlertasFuentes(_BaseDB):
    def _tipos(self, fuente):
        return {a["tipo"] for a in calcular_alertas(self.db) if a.get("fuente") == fuente}

    def test_fuente_vacia_repetida_genera_una_sola_alerta(self):
        for _ in range(2):
            self.db.registrar_salud_fuente("infoyungas", "ok", elementos_obtenidos=0)
        self.assertNotIn("fuente_vacia", self._tipos("infoyungas"))
        self.db.registrar_salud_fuente("infoyungas", "ok", elementos_obtenidos=0)
        self.assertEqual(self._tipos("infoyungas"), {"fuente_vacia"})
        self.db.registrar_salud_fuente("infoyungas", "ok", elementos_obtenidos=5, noticias_nuevas=1)
        self.assertNotIn("fuente_vacia", self._tipos("infoyungas"))

    def test_items_sin_texto(self):
        self.db.registrar_salud_fuente("tribuno-jujuy", "ok", elementos_obtenidos=10, noticias_nuevas=1, items_sin_texto=8)
        self.assertIn("fuente_sin_texto", self._tipos("tribuno-jujuy"))

    def test_certificado_y_parser_alertan_de_inmediato_http_al_repetirse(self):
        self.db.registrar_salud_fuente("a", "error", mensaje_error="<urlopen error [SSL: CERTIFICATE_VERIFY_FAILED]>")
        self.db.registrar_salud_fuente("b", "error", mensaje_error="Error inesperado: not well-formed (invalid token)")
        self.db.registrar_salud_fuente("c", "error", mensaje_error="Respondió HTTP 503 (Service Unavailable) al pedir x")
        self.assertEqual(self._tipos("a"), {"fuente_error_certificado"})
        self.assertEqual(self._tipos("b"), {"fuente_error_parser"})
        self.assertEqual(self._tipos("c"), set())
        self.db.registrar_salud_fuente("c", "error", mensaje_error="Respondió HTTP 503 (Service Unavailable) al pedir x")
        self.assertEqual(self._tipos("c"), {"fuente_error_http"})
        self.db.registrar_salud_fuente("c", "error", mensaje_error="Respondió HTTP 503 (Service Unavailable) al pedir x")
        self.assertEqual(self._tipos("c"), {"fuente_con_fallas"})


class TestRSSRegionales(unittest.TestCase):
    def _verificar(self, archivo, nombre, cantidad):
        noticias = parsear_rss_regional((FIXTURES / archivo).read_bytes(), nombre)
        self.assertEqual(len(noticias), cantidad)
        for n in noticias:
            self.assertTrue(n["titulo"])
            self.assertGreaterEqual(len(n["texto"]), 40)
            self.assertTrue(n["url"].startswith("https://"))
            self.assertTrue(n["fecha"])
            self.assertEqual(n["fuente"], nombre)
        return noticias

    def test_infoyungas(self):
        noticias = self._verificar("infoyungas_rss_prueba.xml", "InfoYungas", 2)
        # El %-encoding del feed se decodifica: misma URL que el listado HTML.
        self.assertEqual(noticias[0]["url"],
                         "https://www.infoyungas.com/post/nueva-base-de-la-policía-turística-en-el-acceso-a-las-yungas")
        self.assertTrue(all(n["imagen_url"] for n in noticias))

    def test_jujuy_al_momento(self):
        noticias = self._verificar("jujuyalmomento_rss_prueba.xml", "Jujuy al Momento", 2)
        self.assertIn("Familias van a la escuela", noticias[0]["titulo"])
        self.assertTrue(noticias[0]["imagen_url"])
        self.assertIsNone(noticias[1]["imagen_url"])

    def test_el_tribuno(self):
        noticias = self._verificar("tribuno_jujuy_rss_prueba.xml", "El Tribuno de Jujuy", 2)
        self.assertTrue(noticias[0]["imagen_url"].startswith("https://uscdn.eltribunodejujuy.com/"))

    def test_collectors_leen_el_feed_configurado(self):
        casos = (
            (InfoYungasRSSCollector, "infoyungas_rss_prueba.xml", "https://www.infoyungas.com/blog-feed.xml"),
            (JujuyAlMomentoRSSCollector, "jujuyalmomento_rss_prueba.xml", "https://www.jujuyalmomento.com/rss/pages/home.xml"),
            (TribunoJujuyRSSCollector, "tribuno_jujuy_rss_prueba.xml", "https://eltribunodejujuy.com/feed"),
        )
        for clase, archivo, url in casos:
            with self.subTest(clase=clase.__name__):
                collector = clase()
                self.assertEqual(collector.url_rss, url)
                with patch("motor_noticias.collectors.rss_regionales.obtener_rss",
                           return_value=(FIXTURES / archivo).read_bytes()):
                    self.assertEqual(len(collector.recolectar()), 2)
                self.assertEqual(collector.origen_ultima_lectura, "rss")

    def test_feed_caido_usa_el_listado_html_de_respaldo(self):
        collector = InfoYungasRSSCollector()
        respaldo = [{"titulo": "Nota HTML", "texto": "x", "url": "https://www.infoyungas.com/post/x", "fuente": "InfoYungas"}]
        with patch("motor_noticias.collectors.rss_regionales.obtener_rss",
                   side_effect=ErrorRecoleccionRSSGenerico("Respondió HTTP 500")), \
                patch.object(InfoYungasRSSCollector.COLLECTOR_HTML, "recolectar", return_value=respaldo):
            self.assertEqual(collector.recolectar(), respaldo)
        self.assertEqual(collector.origen_ultima_lectura, "html")

    def test_feed_roto_usa_el_respaldo(self):
        collector = TribunoJujuyRSSCollector()
        with patch("motor_noticias.collectors.rss_regionales.obtener_rss", return_value=b"<rss><channel><item>"), \
                patch.object(TribunoJujuyRSSCollector.COLLECTOR_HTML, "recolectar", return_value=[]):
            self.assertEqual(collector.recolectar(), [])
        self.assertEqual(collector.origen_ultima_lectura, "html")


if __name__ == "__main__":
    unittest.main()
