"""Canal rápido de noticias locales (panel → "Cargar noticia local",
9/10/2026). Nunca hace requests de red: la lectura de URL se reemplaza por
un stub y las URLs de redes sociales se rechazan antes de cualquier red."""
import http.client
import tempfile
import threading
import unittest
from http.server import HTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlencode

from motor_noticias.db import Database
from motor_noticias.dedupe import normalizar_url
from motor_noticias.ingreso_manual import ErrorIngresoManual, cargar_noticia_local
from motor_noticias.lectura_url import (
    ErrorLecturaURL,
    TextoURL,
    es_enlace_video,
    es_red_social,
    extraer_texto_html,
    leer_texto_url,
)
from motor_noticias.models import Estado
from motor_noticias.panel.server import HOST, PanelHandler
from motor_noticias.pipeline import CATEGORIA_SIN_REDACCION_PROPIA, es_copia_literal_extensa, reintentar_redaccion
from motor_noticias.redaccion.mock import RedactorMock

TEXTO_LIBERTADOR = (
    "Vecinos de Libertador General San Martín reclamaron por el estado de una plaza del barrio "
    "y pidieron a la Municipalidad que intervenga antes de que empiecen las lluvias."
)
TEXTO_CALILEGUA = (
    "Productores de Calilegua presentaron un proyecto de riego comunitario ante las "
    "autoridades locales durante una reunión vecinal realizada en el salón del pueblo."
)
TEXTO_SIN_LUGAR = (
    "Desde la mañana de hoy el servicio de recolección de residuos funciona con demoras por "
    "un desperfecto en uno de los camiones, informaron desde el área de servicios."
)
TEXTO_SENSIBLE = (
    "Un hombre fue imputado en Libertador General San Martín por el robo a un comercio del "
    "centro, según informaron fuentes de la investigación."
)
TEXTO_CORTE_AGUA = (
    "Corte de agua en barrio Jardín de Libertador General San Martín por rotura de caño. Agua "
    "Potable informó que las cuadrillas trabajan para restablecer el servicio durante la tarde."
)
TEXTO_CORTE_AGUA_OTRA_PAGINA = (
    "Corte de agua en el barrio Jardín de Libertador General San Martín por la rotura de un caño "
    "principal. Se estima que el servicio vuelva durante la tarde, informaron vecinos."
)

URL_FB = "https://www.facebook.com/ledesmasoy.Noticias/posts/pfbid0123"


def _stub_lectura(titulo, texto):
    def leer(url):
        return TextoURL(titulo=titulo, texto=texto)
    return leer


def _lectura_prohibida(url):
    raise AssertionError("no debía leerse la URL")


class BaseCanalRapido(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmpdir.name) / "test.db")
        self.redactor = RedactorMock()

    def tearDown(self):
        self.db.close()
        self.tmpdir.cleanup()

    def cargar(self, **kwargs):
        kwargs.setdefault("leer_url", _lectura_prohibida)
        return cargar_noticia_local(self.db, self.redactor, **kwargs)

    def trazas(self):
        return [dict(f) for f in self.db.conn.execute("SELECT * FROM ingreso_rapido_log ORDER BY id")]


class TestEntrada(BaseCanalRapido):
    def test_url_accesible_lee_texto_y_genera_redaccion_propia(self):
        r = self.cargar(
            fuente="InfoYungas", url="https://www.infoyungas.com/post/plaza",
            leer_url=_stub_lectura("Reclamo por una plaza en Libertador", TEXTO_LIBERTADOR),
        )
        self.assertEqual(r.resultado, "preparada")
        self.assertEqual(r.origen_texto, "url")
        noticia = self.db.obtener(r.manual.noticia_id)
        self.assertEqual(noticia["url_fuente"], "https://www.infoyungas.com/post/plaza")
        self.assertEqual(noticia["origen_ingreso"], "manual")
        self.assertTrue(noticia["texto_preparado"])

    def test_facebook_sin_texto_pide_pegar_el_texto_sin_leer_la_url(self):
        with self.assertRaises(ErrorIngresoManual) as ctx:
            cargar_noticia_local(self.db, self.redactor, fuente="Ledesma Soy", url=URL_FB)
        self.assertIn("Pegá el texto", str(ctx.exception))
        self.assertEqual(self.db.listar(), [])

    def test_facebook_con_texto_manual(self):
        r = self.cargar(fuente="Ledesma Soy", url=URL_FB, texto=TEXTO_LIBERTADOR)
        self.assertEqual(r.resultado, "preparada")
        self.assertEqual(r.origen_texto, "manual")
        self.assertEqual(self.db.obtener(r.manual.noticia_id)["url_fuente"], URL_FB)

    def test_sin_url_ni_texto_es_error(self):
        with self.assertRaises(ErrorIngresoManual):
            self.cargar(fuente="Ledesma Soy")

    def test_sitio_caido_pide_texto(self):
        def falla(url):
            raise ErrorLecturaURL("no se pudo conectar con el sitio.")
        with self.assertRaises(ErrorIngresoManual) as ctx:
            self.cargar(fuente="Canal 6 Libertador", url="https://canalseis.com.ar/nota", leer_url=falla)
        self.assertIn("Pegá el texto", str(ctx.exception))


class TestDeduplicacion(BaseCanalRapido):
    def test_misma_publicacion_con_variantes_de_url_de_facebook(self):
        primera = self.cargar(fuente="Ledesma Soy", url=URL_FB, texto=TEXTO_LIBERTADOR)
        segunda = self.cargar(
            fuente="Ledesma Soy",
            url="https://m.facebook.com/ledesmasoy.Noticias/posts/pfbid0123/?mibextid=abc&rdid=xyz",
            texto="Otro texto cualquiera pegado por el operador sobre la misma publicación local.",
        )
        self.assertEqual(segunda.resultado, "duplicado")
        self.assertEqual(segunda.duplicado_de["id"], primera.manual.noticia_id)
        self.assertEqual(len(self.db.listar()), 1)

    def test_mismo_hecho_desde_otra_pagina_se_consolida(self):
        primera = self.cargar(fuente="Ledesma Soy", url=URL_FB, texto=TEXTO_CORTE_AGUA)
        segunda = self.cargar(
            fuente="FM Radio Speed 96.7", url="https://www.facebook.com/fmradiospeed/posts/9",
            texto=TEXTO_CORTE_AGUA_OTRA_PAGINA,
        )
        self.assertEqual(segunda.resultado, "mismo_hecho")
        self.assertEqual(segunda.duplicado_de["id"], primera.manual.noticia_id)
        self.assertEqual(len(self.db.listar()), 1)

    def test_mismo_hecho_forzado_por_el_operador(self):
        self.cargar(fuente="Ledesma Soy", url=URL_FB, texto=TEXTO_CORTE_AGUA)
        segunda = self.cargar(
            fuente="FM Radio Speed 96.7", url="https://www.facebook.com/fmradiospeed/posts/9",
            texto=TEXTO_CORTE_AGUA_OTRA_PAGINA + " Libertador General San Martín.",
            forzar_no_duplicado=True,
        )
        self.assertNotEqual(segunda.resultado, "mismo_hecho")
        self.assertEqual(len(self.db.listar()), 2)

    def test_mismo_video_compartido_por_dos_medios(self):
        self.cargar(fuente="Ledesma Soy", url="https://fb.watch/abc123/", texto=TEXTO_CORTE_AGUA)
        otro = self.cargar(
            fuente="INFO Yungas (Facebook)", url="https://www.facebook.com/infoyungas1/videos/555",
            texto=TEXTO_CORTE_AGUA_OTRA_PAGINA,
        )
        self.assertEqual(otro.resultado, "mismo_hecho")

    def test_normalizacion_solo_limpia_parametros_de_redes_en_sus_hosts(self):
        self.assertEqual(
            normalizar_url("https://web.facebook.com/p/posts/1?mibextid=x&s=y"),
            normalizar_url("https://facebook.com/p/posts/1/"),
        )
        self.assertNotEqual(
            normalizar_url("https://ejemplo.com/nota?ref=1"), normalizar_url("https://ejemplo.com/nota?ref=2")
        )


class TestEditorial(BaseCanalRapido):
    def test_urgente_se_respeta(self):
        r = self.cargar(fuente="Bomberos Voluntarios LGSM", url=URL_FB, texto=TEXTO_LIBERTADOR, urgente=True)
        self.assertTrue(self.db.obtener(r.manual.noticia_id)["urgente"])

    def test_sensible_queda_para_revision_humana(self):
        r = self.cargar(fuente="Ledesma Soy", url=URL_FB, texto=TEXTO_SENSIBLE, urgente=True)
        noticia = self.db.obtener(r.manual.noticia_id)
        self.assertTrue(noticia["requiere_revision_especial"])
        self.assertEqual(self.db.candidatas_portal("2000-01-01"), [])

    def test_sin_imagen_no_toma_ninguna_imagen(self):
        r = self.cargar(fuente="Ledesma Soy", url=URL_FB, texto=TEXTO_LIBERTADOR)
        noticia = self.db.obtener(r.manual.noticia_id)
        self.assertFalse(noticia["tiene_imagen_original"])
        self.assertFalse(noticia["imagen_publicacion_ruta"])

    def test_imagen_propia_autorizada(self):
        r = self.cargar(
            fuente="Ledesma Soy", url=URL_FB, texto=TEXTO_LIBERTADOR,
            imagen_url="https://ledesmaparticipa.com.ar/fotos/propia.jpg",
        )
        self.assertTrue(self.db.obtener(r.manual.noticia_id)["tiene_imagen_original"])

    def test_video_conserva_solo_el_enlace(self):
        r = self.cargar(fuente="Canal 6 Libertador", url="https://fb.watch/xyz/", texto=TEXTO_LIBERTADOR)
        self.assertTrue(r.es_video)
        noticia = self.db.obtener(r.manual.noticia_id)
        self.assertEqual(noticia["url_fuente"], "https://fb.watch/xyz/")
        self.assertIn("video", noticia["observacion_interna"])
        self.assertFalse(noticia["tiene_imagen_original"])

    def test_fuente_desconocida_se_procesa_y_queda_marcada(self):
        r = self.cargar(fuente="Página Vecinal X", url=URL_FB, texto=TEXTO_LIBERTADOR)
        self.assertIsNone(r.fuente_padron)
        self.assertEqual(r.resultado, "preparada")
        self.assertIn("fuera del padrón", self.db.obtener(r.manual.noticia_id)["observacion_interna"])

    def test_fuente_del_padron_y_pendiente(self):
        self.assertEqual(self.cargar(fuente="ledesma soy", texto=TEXTO_LIBERTADOR).fuente_padron.clasificacion, "B")
        pendiente = self.cargar(fuente="FM Orión", texto=TEXTO_CALILEGUA)
        self.assertIsNotNone(pendiente.fuente_padron)
        self.assertIsNone(pendiente.fuente_padron.clasificacion)

    def test_clasificacion_libertador(self):
        r = self.cargar(fuente="Ledesma Soy", texto=TEXTO_LIBERTADOR)
        self.assertEqual(r.manual.territorio, "local")

    def test_clasificacion_departamento_ledesma(self):
        r = self.cargar(fuente="Frecuencia Calilegua FM (106.7)", texto=TEXTO_CALILEGUA)
        self.assertEqual(r.manual.territorio, "departamental")

    def test_territorio_informado_solo_como_respaldo(self):
        r = self.cargar(fuente="YUTO INFORMA", texto=TEXTO_SIN_LUGAR, territorio_informado="Yuto")
        self.assertEqual(r.manual.territorio, "departamental")
        self.assertTrue(r.territorio_respaldo_usado)
        manda_el_texto = self.cargar(
            fuente="Ledesma Soy", texto=TEXTO_LIBERTADOR, territorio_informado="Yuto", forzar_no_duplicado=True
        )
        self.assertEqual(manda_el_texto.manual.territorio, "local")
        self.assertFalse(manda_el_texto.territorio_respaldo_usado)

    def test_no_programa_nada_en_redes(self):
        self.cargar(fuente="Ledesma Soy", url=URL_FB, texto=TEXTO_LIBERTADOR)
        self.assertEqual(self.db.conn.execute("SELECT COUNT(*) FROM programacion_meta").fetchone()[0], 0)

    def test_trazabilidad(self):
        r = self.cargar(fuente="Ledesma Soy", url=URL_FB, texto=TEXTO_LIBERTADOR)
        self.cargar(fuente="Ledesma Soy", url=URL_FB, texto=TEXTO_LIBERTADOR)
        primera, segunda = self.trazas()
        self.assertEqual(primera["fuente"], "Ledesma Soy")
        self.assertEqual(primera["url_original"], URL_FB)
        self.assertEqual(primera["canal"], "panel")
        self.assertEqual(primera["noticia_id"], r.manual.noticia_id)
        self.assertEqual(primera["estado"], Estado.PREPARADA.value)
        self.assertEqual(primera["resultado"], "preparada")
        self.assertTrue(primera["fecha_hora"])
        self.assertEqual(segunda["resultado"], "duplicado")
        self.assertEqual(segunda["duplicado_de"], r.manual.noticia_id)


class TestLecturaURL(unittest.TestCase):
    def test_redes_sociales_y_videos(self):
        self.assertTrue(es_red_social("https://m.facebook.com/x/posts/1"))
        self.assertTrue(es_red_social("https://www.instagram.com/p/abc/"))
        self.assertFalse(es_red_social("https://www.infoyungas.com/post/x"))
        self.assertTrue(es_enlace_video("https://www.facebook.com/x/videos/1"))
        self.assertTrue(es_enlace_video("https://www.facebook.com/reel/1"))
        self.assertFalse(es_enlace_video("https://www.facebook.com/x/posts/1"))

    def test_red_social_nunca_se_descarga(self):
        with self.assertRaises(ErrorLecturaURL):
            leer_texto_url(URL_FB, descargar=_lectura_prohibida)

    def test_host_interno_rechazado(self):
        with self.assertRaises(ErrorLecturaURL):
            leer_texto_url("http://127.0.0.1:8000/estado", descargar=_lectura_prohibida)

    def test_extrae_titulo_y_parrafos_sin_imagen(self):
        html = """<html><head><title>Sitio</title>
        <meta property="og:title" content="Corte de agua en Libertador">
        <meta property="og:image" content="https://medio.com/foto.jpg"></head>
        <body><nav><p>Menú del sitio con enlaces varios que no son parte de la nota.</p></nav>
        <article><p>Agua Potable informó un corte de servicio en el barrio Jardín de Libertador.</p>
        <p>Corto.</p></article><script>var x = "<p>no</p>";</script></body></html>"""
        resultado = extraer_texto_html(html)
        self.assertEqual(resultado.titulo, "Corte de agua en Libertador")
        self.assertIn("barrio Jardín", resultado.texto)
        self.assertNotIn("Menú", resultado.texto)
        self.assertNotIn("foto.jpg", resultado.texto)


class RedactorCaido:
    def redactar(self, noticia):
        raise TimeoutError("Ollama no responde")


class TestPanelCargaLocalHTTP(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "test.db"
        Database(self.db_path).close()
        PanelHandler.db_path = self.db_path
        self.servidor = HTTPServer((HOST, 0), PanelHandler)
        self.puerto = self.servidor.server_address[1]
        self.hilo = threading.Thread(target=self.servidor.serve_forever, daemon=True)
        self.hilo.start()

    def tearDown(self):
        self.servidor.shutdown()
        self.servidor.server_close()
        self.hilo.join(timeout=5)
        self.tmpdir.cleanup()

    def _pedir(self, metodo, ruta, datos=None):
        conn = http.client.HTTPConnection(HOST, self.puerto, timeout=5)
        cuerpo = urlencode(datos) if datos is not None else None
        conn.request(metodo, ruta, body=cuerpo, headers={"Content-Type": "application/x-www-form-urlencoded"})
        resp = conn.getresponse()
        texto = resp.read().decode("utf-8")
        conn.close()
        return resp.status, texto

    def _noticias(self):
        db = Database(self.db_path)
        try:
            return db.listar()
        finally:
            db.close()

    def test_formulario(self):
        status, cuerpo = self._pedir("GET", "/cargar-noticia-local")
        self.assertEqual(status, 200)
        for campo in ('name="url"', 'name="fuente"', 'name="texto"', 'name="territorio"', 'name="urgente"', "PROCESAR"):
            self.assertIn(campo, cuerpo)
        self.assertIn("Ledesma Soy", cuerpo)  # datalist del padrón
        self.assertIn("Cargar noticia local", self._pedir("GET", "/")[1])

    def test_facebook_sin_texto(self):
        status, cuerpo = self._pedir("POST", "/cargar-noticia-local", {"fuente": "Ledesma Soy", "url": URL_FB})
        self.assertEqual(status, 400)
        self.assertIn("Pegá el texto", cuerpo)
        self.assertIn(URL_FB, cuerpo)  # conserva lo cargado

    def test_procesa_y_detecta_mismo_hecho(self):
        status, cuerpo = self._pedir(
            "POST", "/cargar-noticia-local", {"fuente": "Ledesma Soy", "url": URL_FB, "texto": TEXTO_CORTE_AGUA}
        )
        self.assertEqual(status, 200)
        self.assertIn("resultado", cuerpo)
        status, cuerpo = self._pedir(
            "POST", "/cargar-noticia-local",
            {"fuente": "FM Radio Speed 96.7", "url": "https://www.facebook.com/fmradiospeed/posts/9",
             "texto": TEXTO_CORTE_AGUA_OTRA_PAGINA},
        )
        self.assertEqual(status, 409)
        self.assertIn("forzar_no_duplicado", cuerpo)
        self.assertEqual(len(self._noticias()), 1)

    def test_redaccion_caida_queda_en_revision_sin_copiar(self):
        with patch.object(PanelHandler, "redactor", RedactorCaido()):
            status, cuerpo = self._pedir(
                "POST", "/cargar-noticia-local", {"fuente": "Ledesma Soy", "url": URL_FB, "texto": TEXTO_LIBERTADOR}
            )
        self.assertEqual(status, 200)
        self.assertIn("Sin redacción propia", cuerpo)
        noticia = self._noticias()[0]
        self.assertEqual(noticia["categoria_riesgo"], CATEGORIA_SIN_REDACCION_PROPIA)

    def test_boton_reintentar_redaccion(self):
        with patch.object(PanelHandler, "redactor", RedactorCaido()):
            self._pedir("POST", "/cargar-noticia-local", {"fuente": "Ledesma Soy", "url": URL_FB, "texto": TEXTO_LARGO})
        id_noticia = self._noticias()[0]["id"]
        status, cuerpo = self._pedir("GET", f"/noticia?id={id_noticia}")
        self.assertIn('value="reintentar_redaccion"', cuerpo)
        self.assertNotIn(f"<textarea name=\"texto_revisado\">{TEXTO_LARGO[:40]}", cuerpo)
        status, cuerpo = self._pedir("POST", f"/noticia?id={id_noticia}", {"accion": "reintentar_redaccion"})
        self.assertEqual(status, 200)
        self.assertIn("vuelve al circuito normal", cuerpo)
        self.assertIsNone(self._noticias()[0]["categoria_riesgo"])


TEXTO_LARGO = (
    "Vecinos de Libertador General San Martín contaron que durante toda la semana se realizarán "
    "trabajos de bacheo en las avenidas principales de la ciudad, por lo que habrá desvíos de tránsito "
    "en distintos horarios. Se recomienda a los conductores circular con precaución, respetar la "
    "señalización y prever demoras en los traslados hacia el centro y los barrios de la zona norte."
)


class RedactorCopia:
    """Simula el fallback seguro del redactor: devuelve el texto de la fuente."""

    def redactar(self, noticia):
        return noticia.titulo_original, noticia.texto_original


class TestSinRedaccionPropia(BaseCanalRapido):
    def test_fallo_de_redaccion_queda_en_revision_y_fuera_de_todo_circuito(self):
        r = cargar_noticia_local(self.db, RedactorCaido(), fuente="Ledesma Soy", url=URL_FB, texto=TEXTO_LARGO, urgente=True)
        noticia = self.db.obtener(r.manual.noticia_id)
        self.assertEqual(noticia["estado"], Estado.PREPARADA.value)
        self.assertTrue(noticia["requiere_revision_especial"])
        self.assertEqual(noticia["categoria_riesgo"], CATEGORIA_SIN_REDACCION_PROPIA)
        self.assertEqual(noticia["texto_original"], TEXTO_LARGO)  # referencia interna
        self.assertEqual(self.db.candidatas_portal("2000-01-01"), [])
        self.assertNotIn(noticia["id"], [n["id"] for n in self.db.candidatos_editoriales(set(), "2000-01-01")])

    def test_copia_literal_extensa_queda_en_revision(self):
        r = cargar_noticia_local(self.db, RedactorCopia(), fuente="Ledesma Soy", url=URL_FB, texto=TEXTO_LARGO)
        noticia = self.db.obtener(r.manual.noticia_id)
        self.assertEqual(noticia["categoria_riesgo"], CATEGORIA_SIN_REDACCION_PROPIA)
        self.assertEqual(self.db.candidatas_portal("2000-01-01"), [])

    def test_cita_breve_no_se_retiene(self):
        self.assertFalse(es_copia_literal_extensa(TEXTO_LIBERTADOR, TEXTO_LIBERTADOR))
        self.assertTrue(es_copia_literal_extensa(TEXTO_LARGO, TEXTO_LARGO))
        self.assertTrue(es_copia_literal_extensa(TEXTO_LARGO + " Más datos al final.", TEXTO_LARGO))
        self.assertFalse(es_copia_literal_extensa(TEXTO_LARGO, "Texto propio. " + TEXTO_LARGO[::-1]))

    def test_collector_con_ollama_caido_tambien_queda_en_revision(self):
        from motor_noticias.pipeline import normalizar_noticia, procesar_noticia
        noticia = normalizar_noticia({"titulo": "Bacheo en Libertador General San Martín", "texto": TEXTO_LARGO,
                                      "url": "https://medio.test/bacheo", "fuente": "InfoYungas"})
        noticia, resultado = procesar_noticia(self.db, noticia, RedactorCaido(), tolerar_fallo_redaccion=True)
        self.assertEqual(resultado, "preparada")
        self.assertEqual(self.db.obtener(noticia.id)["categoria_riesgo"], CATEGORIA_SIN_REDACCION_PROPIA)

    def test_informe_diario_y_contenido_propio_no_son_copia_literal(self):
        # Caso real 10/10/2026: el informe Clima + Dólar (#80075) quedó
        # retenido como "sin redacción propia" y no salió a las 07:30.
        from motor_noticias.contenido_propio import _RedactorIdentidad as RedactorContenidoPropio
        from motor_noticias.informe_diario import _RedactorIdentidad as RedactorInforme
        from motor_noticias.pipeline import normalizar_noticia, procesar_noticia
        for i, redactor in enumerate((RedactorInforme(), RedactorContenidoPropio())):
            noticia = normalizar_noticia({"titulo": f"Clima + Dólar | Informe de la mañana {i}", "texto": TEXTO_LARGO + str(i),
                                          "url": f"https://ledesmaparticipa.test/informe/{i}", "fuente": "Ledesma Participa"})
            noticia, resultado = procesar_noticia(self.db, noticia, redactor)
            self.assertEqual(resultado, "preparada")
            self.assertNotEqual(self.db.obtener(noticia.id)["categoria_riesgo"], CATEGORIA_SIN_REDACCION_PROPIA)

    def test_reintento_libera_solo_con_redaccion_propia(self):
        r = cargar_noticia_local(self.db, RedactorCaido(), fuente="Ledesma Soy", url=URL_FB, texto=TEXTO_LARGO)
        id_noticia = r.manual.noticia_id
        liberada, _ = reintentar_redaccion(self.db, id_noticia, RedactorCaido())
        self.assertFalse(liberada)
        liberada, _ = reintentar_redaccion(self.db, id_noticia, RedactorCopia())
        self.assertFalse(liberada)
        self.assertEqual(self.db.obtener(id_noticia)["categoria_riesgo"], CATEGORIA_SIN_REDACCION_PROPIA)
        liberada, _ = reintentar_redaccion(self.db, id_noticia, RedactorMock())
        self.assertTrue(liberada)
        noticia = self.db.obtener(id_noticia)
        self.assertFalse(noticia["requiere_revision_especial"])
        self.assertNotEqual(noticia["texto_preparado"], TEXTO_LARGO)
        self.assertEqual(len(self.db.candidatas_portal("2000-01-01")), 1)

    def test_reintento_no_aplica_a_otras_retenidas(self):
        r = self.cargar(fuente="Ledesma Soy", url=URL_FB, texto=TEXTO_SENSIBLE)
        liberada, mensaje = reintentar_redaccion(self.db, r.manual.noticia_id, RedactorMock())
        self.assertFalse(liberada)
        self.assertTrue(self.db.obtener(r.manual.noticia_id)["requiere_revision_especial"])


class TestTerritorioLocal(BaseCanalRapido):
    TEXTO_SOLO_LIBERTADOR = (
        "Corte de agua en barrio Jardín de Libertador por la rotura de un caño. Las cuadrillas "
        "trabajan para restablecer el servicio durante la tarde."
    )

    def test_libertador_desde_fuente_local_del_padron(self):
        r = self.cargar(fuente="Ledesma Soy", texto=self.TEXTO_SOLO_LIBERTADOR)
        self.assertEqual(r.manual.territorio, "local")
        self.assertFalse(r.territorio_respaldo_usado)

    def test_lgsm_y_nombre_completo(self):
        r = self.cargar(fuente="Página Vecinal X", texto="Corte de luz programado en LGSM para el jueves por obras de la distribuidora eléctrica.")
        self.assertEqual(r.manual.territorio, "local")
        r = self.cargar(fuente="Página Vecinal X", texto=TEXTO_LIBERTADOR)
        self.assertEqual(r.manual.territorio, "local")

    def test_libertador_ambiguo_pide_territorio(self):
        with self.assertRaises(ErrorIngresoManual) as ctx:
            self.cargar(fuente="Página Vecinal X", texto=self.TEXTO_SOLO_LIBERTADOR)
        self.assertIn("Territorio", str(ctx.exception))
        self.assertEqual(self.db.listar(), [])
        self.assertEqual(self.trazas()[-1]["resultado"], "territorio_ambiguo")
        r = self.cargar(
            fuente="Página Vecinal X", texto=self.TEXTO_SOLO_LIBERTADOR,
            territorio_informado="Libertador General San Martín",
        )
        self.assertEqual(r.manual.territorio, "local")
        self.assertTrue(r.territorio_respaldo_usado)

    def test_libertador_con_contexto_jujeno(self):
        r = self.cargar(fuente="Página Vecinal X", texto=self.TEXTO_SOLO_LIBERTADOR + " Hay demoras sobre la Ruta 34.")
        self.assertEqual(r.manual.territorio, "local")

    def test_padron_local_sincronizado_con_medios_locales(self):
        import json
        raiz = Path(__file__).resolve().parent.parent
        padron = json.load(open(raiz / "config" / "fuentes_locales.json", encoding="utf-8"))
        locales = json.load(open(raiz / "config" / "localidades.json", encoding="utf-8"))["medios_locales"]["terminos"]
        nombres = [f["nombre"] for f in padron["fuentes"] if not f["localidad"].startswith("Provincial")]
        nombres += [f["nombre"] for f in padron["pendientes_de_confirmar"]]
        self.assertEqual([n for n in nombres if n not in locales], [])


class TestHechosDistintosParecidos(BaseCanalRapido):
    def test_mismo_aviso_en_localidades_distintas_no_se_consolida(self):
        a = self.cargar(fuente="Frecuencia Calilegua FM (106.7)", url="https://www.facebook.com/fcal/posts/1",
                        texto="Corte de energía en Calilegua por tareas de mantenimiento de la red el martes por la mañana.")
        b = self.cargar(fuente="YUTO INFORMA", url="https://www.facebook.com/YutoInforma/posts/2",
                        texto="Corte de energía en Yuto por tareas de mantenimiento de la red el martes por la mañana.")
        self.assertEqual(a.resultado, "preparada")
        self.assertEqual(b.resultado, "preparada")

    def test_mismo_aviso_en_fechas_distintas_no_se_consolida(self):
        a = self.cargar(fuente="Ledesma Soy", url="https://www.facebook.com/ls/posts/1",
                        texto="Corte de agua en Libertador General San Martín el 12/10 por obras en la red de distribución.")
        b = self.cargar(fuente="Ledesma Soy", url="https://www.facebook.com/ls/posts/2",
                        texto="Corte de agua en Libertador General San Martín el 19/10 por obras en la red de distribución.")
        self.assertEqual(a.resultado, "preparada")
        self.assertEqual(b.resultado, "preparada")

if __name__ == "__main__":
    unittest.main()
