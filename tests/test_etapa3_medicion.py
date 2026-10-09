"""Etapa 3 — medición, crecimiento y optimización: content_id, formatos,
métricas Meta (NO DISPONIBLE explícito), medición agregada sin PII,
ranking, alertas, SEO/Open Graph, relacionadas, CTA, Guía Comercial y
Radios. Todo aislado: sin red, sin data/ real."""
import json
import re
import shutil
import subprocess
import tempfile
import threading
import unittest
import urllib.request
from datetime import date
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from motor_noticias import contenido_registro, crecimiento, medicion, metricas_meta, titulares
from motor_noticias.db import Database
from motor_noticias.models import Estado, Noticia, RevisionEstado
from motor_noticias.sitio import plantillas
from motor_noticias.sitio.generador import generar_sitio, relacionadas_para

from tests.test_generar_sitio_web import _aislar

ASSETS = Path(__file__).resolve().parent.parent / "motor_noticias" / "sitio" / "assets_fuente"


def _noticia(**overrides) -> Noticia:
    base = dict(
        id=None,
        titulo_original="Corte de agua programado en Libertador General San Martín",
        texto_original="Texto original",
        url_fuente="https://ejemplo.test/nota",
        url_normalizada="https://ejemplo.test/nota",
        nombre_fuente="Fuente Ejemplo",
        fecha_fuente="Fri, 09 Oct 2026 10:00:00 -0300",
        fecha_recoleccion="2026-10-09T13:00:00+00:00",
        estado=Estado.PUBLICADA.value,
        hash_contenido="h",
        titulo_preparado="Corte de agua programado en Libertador General San Martín",
        texto_preparado="La empresa informó un corte de agua en Libertador General San Martín. El servicio se repondrá a la tarde.",
        revision_estado=RevisionEstado.APROBADA.value,
        territorio="local",
    )
    base.update(overrides)
    return Noticia(**base)


class _ConDB(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "t.db")

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def _guardar(self, **kw) -> dict:
        noticia_id = self.db.guardar(_noticia(**kw))
        return self.db.obtener(noticia_id)

    def _publicar(self, noticia_id, fecha, hora, red, meta_id):
        prog = self.db.reservar_programacion_meta(fecha, hora, noticia_id, red, "2026-10-09T10:00:00+00:00")
        self.db.actualizar_programacion_meta(prog, "publicado", meta_id=meta_id, publicada_en="2026-10-09T10:30:00+00:00")


class TestContentId(_ConDB):
    def test_formato_unico_e_idempotente(self):
        a = self._guardar(hash_contenido="a")
        b = self._guardar(hash_contenido="b", url_normalizada="https://ejemplo.test/b")
        id_a = contenido_registro.registrar_publicacion(self.db, a, fecha="2026-10-09", clave="07:30", imagen_generada=True)
        id_b = contenido_registro.registrar_publicacion(self.db, b, fecha="2026-10-09", clave="07:30", imagen_generada=False)
        self.assertEqual(id_a, "lp_20261009_0730_001")
        self.assertEqual(id_b, "lp_20261009_0730_002")
        self.assertRegex(id_a, r"^lp_\d{8}_\d{4}_\d{3}$")
        # Segunda red / reintento: mismo content_id, sin fila nueva.
        self.assertEqual(contenido_registro.registrar_publicacion(self.db, a, fecha="2026-10-09", clave="09:00", imagen_generada=True), id_a)
        self.assertEqual(self.db.conn.execute("SELECT COUNT(*) FROM contenido_registro").fetchone()[0], 2)

    def test_urgente_usa_hora_real_y_formato_rojo(self):
        n = self._guardar(hash_contenido="u")
        cid = contenido_registro.registrar_publicacion(
            self.db, n, fecha="2026-10-09", clave="urgente-12", imagen_generada=True,
            publicada_en="2026-10-09T14:05:00+00:00",
        )
        fila = contenido_registro.obtener_por_noticia(self.db, n["id"])
        self.assertEqual(cid, "lp_20261009_1105_001")  # 14:05 UTC = 11:05 Jujuy
        self.assertEqual(fila["visual_format"], "URGENT_CARD")
        self.assertEqual(fila["urgente"], 1)
        self.assertEqual(fila["reel_candidate"], 1)

    def test_registro_completo_sin_datos_personales(self):
        n = self._guardar(hash_contenido="c")
        contenido_registro.registrar_publicacion(
            self.db, n, fecha="2026-10-09", clave="09:00", imagen_generada=False,
            texto_publicado="Texto https://ledesmaparticipa.com.ar/noticias/1-x/", url_web="https://ledesmaparticipa.com.ar/noticias/1-x/",
        )
        fila = contenido_registro.obtener_por_noticia(self.db, n["id"])
        for campo in ("content_id", "fecha", "hora", "territorio", "categoria", "urgente", "visual_format", "fuente",
                      "propia", "url_web", "has_real_photo", "has_video", "has_link"):
            self.assertIn(campo, fila)
        self.assertEqual(fila["visual_format"], "PHOTO_HEADLINE")
        self.assertEqual(fila["has_real_photo"], 1)
        self.assertEqual(fila["has_link"], 1)
        self.assertEqual(fila["propia"], 0)
        columnas = {c[1] for c in self.db.conn.execute("PRAGMA table_info(contenido_registro)")}
        self.assertFalse(columnas & {"ip", "email", "telefono", "usuario", "user_id", "device_id"})

    def test_historico_se_registra_con_formato_inferido_y_ids_de_plataforma(self):
        n = self._guardar(hash_contenido="h1", imagen_generada_automaticamente=True)
        self._publicar(n["id"], "2026-10-08", "21:00", "facebook", "fb_1")
        self._publicar(n["id"], "2026-10-08", "21:00", "instagram", "ig_1")
        self._publicar(n["id"], "2026-10-08", "21:00", "instagram_story", "st_1")
        self.assertEqual(contenido_registro.sincronizar_historico(self.db), 1)
        self.assertEqual(contenido_registro.sincronizar_historico(self.db), 0)
        (c,) = contenido_registro.listar_con_plataformas(self.db, "2026-10-01")
        self.assertEqual(c["content_id"], "lp_20261008_2100_001")
        self.assertEqual(c["formato_inferido"], 1)
        self.assertEqual(c["visual_format"], "EDITORIAL_CARD")
        self.assertEqual((c["facebook_post_id"], c["instagram_media_id"], c["instagram_story_id"]), ("fb_1", "ig_1", "st_1"))

    def test_fallo_del_registro_no_rompe_la_publicacion(self):
        from motor_noticias.meta import publicador

        class Contenido:
            imagen_generada_automaticamente = True
            post_principal = ""

        with patch("motor_noticias.contenido_registro.registrar_publicacion", side_effect=RuntimeError("x")):
            publicador._registrar_contenido(self.db, {"id": 1}, "2026-10-09", "09:00", Contenido())  # no lanza


class TestFormatos(unittest.TestCase):
    def test_formatos_visuales(self):
        f = contenido_registro.formato_visual
        self.assertEqual(f({}, urgente=True, imagen_generada=False), "URGENT_CARD")
        self.assertEqual(f({"origen_ingreso": "institucional"}, urgente=False, imagen_generada=True), "INSTITUTIONAL")
        self.assertEqual(f({}, urgente=False, imagen_generada=True, categoria="servicios"), "SERVICE_CARD")
        self.assertEqual(f({}, urgente=False, imagen_generada=False), "PHOTO_HEADLINE")
        self.assertEqual(f({}, urgente=False, imagen_generada=True), "EDITORIAL_CARD")
        self.assertTrue({"STORY", "CAROUSEL", "REEL", "EXTERNAL_IMAGE"} <= set(contenido_registro.FORMATOS_VISUALES))

    def test_reel_candidato_solo_con_senal_concreta(self):
        r = contenido_registro.es_reel_candidato
        self.assertTrue(r({}, urgente=True, categoria=None, puntaje=10))
        self.assertTrue(r({}, urgente=False, categoria=None, puntaje=75))
        self.assertTrue(r({}, urgente=False, categoria="servicios", puntaje=10))
        self.assertFalse(r({}, urgente=False, categoria="deportes", puntaje=40))


class TestTitulares(unittest.TestCase):
    def test_limpia_solo_lo_mecanico(self):
        self.assertEqual(titulares.limpiar_titular("  Corte de agua en  Libertador…"), "Corte de agua en Libertador")
        self.assertEqual(titulares.limpiar_titular("Corte de agua en Libertador"), "Corte de agua en Libertador")

    def test_alertas(self):
        config = {"clickbait": ["no vas a creer"], "exageracion": ["impactante"]}
        self.assertEqual(titulares.evaluar_titular("Corte de agua programado para mañana en Libertador", config)["alertas"], [])
        self.assertIn("largo", titulares.evaluar_titular(" ".join(["palabra"] * 25), config)["alertas"])
        self.assertIn("cortado", titulares.evaluar_titular("El municipio anunció que el corte de...", config)["alertas"])
        self.assertIn("clickbait", titulares.evaluar_titular("No vas a creer lo que pasó en la plaza", config)["alertas"])
        self.assertIn("exageracion", titulares.evaluar_titular("Impactante choque en la ruta 34", config)["alertas"])
        self.assertIn("corto_sin_informacion", titulares.evaluar_titular("Atención vecinos", config)["alertas"])

    def test_encabezado_copy_mantiene_estandar(self):
        from motor_noticias.meta.contenido import encabezado_copy

        with patch("motor_noticias.meta.contenido.etiqueta_territorio_copy", return_value="LIBERTADOR"):
            self.assertEqual(encabezado_copy({}, "Corte de agua en el barrio…"), "LIBERTADOR | CORTE DE AGUA EN EL BARRIO")


class _GetterFalso:
    def __init__(self, respuestas):
        self.respuestas = respuestas

    def __call__(self, path, params):
        clave = params.get("metric") or params.get("fields")
        valor = self.respuestas.get((path.split("/")[-1], clave), self.respuestas.get(clave))
        if isinstance(valor, Exception):
            raise valor
        return valor if valor is not None else {"data": []}


class TestMetricasMeta(_ConDB):
    def test_no_inventa_metricas(self):
        get = _GetterFalso({
            "followers_count": {"followers_count": 420, "id": "1"},
            "media_count": {"media_count": 1297},
            "reach": metricas_meta.ErrorMeta("Application does not have permission for this action"),
        })
        with patch.dict("os.environ", {"META_IG_USER_ID": "ig1"}):
            snap = metricas_meta.obtener_snapshot(self.db, "2026-10-09", get=get)
        self.assertEqual(snap["facebook"]["seguidores"]["valor"], 420)
        # data: [] nunca es cero: NO DISPONIBLE con motivo.
        self.assertEqual(snap["facebook"]["alcance"]["estado"], metricas_meta.NO_DISPONIBLE)
        self.assertIsNone(snap["facebook"]["alcance"]["valor"])
        self.assertEqual(snap["instagram"]["alcance"]["estado"], metricas_meta.NO_DISPONIBLE)
        self.assertIn("permission", snap["instagram"]["alcance"]["motivo"])
        self.assertEqual(snap["instagram"]["stories"]["estado"], metricas_meta.NO_DISPONIBLE)

    def test_insight_con_valores_reales_se_suma(self):
        get = _GetterFalso({"page_media_view": {"data": [{"values": [{"value": 30}, {"value": 12}]}]}})
        valor, _ = metricas_meta._insight(get, "p", "page_media_view", {}, "x")
        self.assertEqual(valor["valor"], 42)

    def test_sin_token_todo_no_disponible(self):
        with patch.dict("os.environ", {}, clear=True):
            snap = metricas_meta.obtener_snapshot(self.db, "2026-10-09")
        self.assertEqual(snap["facebook"]["seguidores"]["estado"], metricas_meta.NO_DISPONIBLE)

    def test_sanitiza_token_y_paginacion(self):
        sucio = {"data": [], "paging": {"previous": "https://g/x?access_token=SECRETO"}, "error": "falló access_token=SECRETO2"}
        limpio = metricas_meta._sanitizar(sucio)
        self.assertNotIn("paging", limpio)
        self.assertNotIn("SECRETO2", json.dumps(limpio))
        ruta = metricas_meta.guardar_snapshot({"fecha": "2026-10-09", "x": sucio}, Path(self.tmp.name))
        self.assertNotIn("SECRETO", ruta.read_text(encoding="utf-8"))

    def test_metricas_por_publicacion_instagram(self):
        n = self._guardar(hash_contenido="ig")
        self._publicar(n["id"], "2026-10-08", "09:00", "instagram", "m1")
        get = _GetterFalso({("m1", "like_count,comments_count"): {"like_count": 4, "comments_count": 1}})
        resumen = metricas_meta.medir_publicaciones_instagram(self.db, get, "2026-10-09")
        self.assertEqual(resumen["medidas"], 1)
        fila = self.db.conn.execute("SELECT * FROM metrica_publicacion").fetchone()
        self.assertEqual((fila["likes"], fila["comentarios"], fila["alcance"]), (4, 1, None))

    def test_baseline_registrada(self):
        base = metricas_meta.leer_baseline()
        self.assertEqual(base["FUENTE"], "auditoría Meta confirmada")
        self.assertEqual(base["facebook"]["seguidores"], 321)
        self.assertEqual(base["instagram"]["visualizaciones"], 2030)
        self.assertEqual(base["instagram"]["stories"], 134)


class TestMedicionSinPII(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.almacen = medicion.AlmacenMedicion(Path(self.tmp.name) / "m.db")

    def tearDown(self):
        self.almacen.close()
        self.tmp.cleanup()

    def test_rechaza_eventos_y_claves_no_permitidas(self):
        n = medicion.normalizar_evento
        self.assertIsNone(n({"e": "evento_inventado"}))
        self.assertIsNone(n({"e": "article_open", "k": "persona@correo.com"}))
        self.assertIsNone(n({"e": "article_open", "k": "3884123456"}))
        self.assertIsNone(n({"e": "article_open", "k": "Juan Pérez"}))
        self.assertIsNone(n({"e": "radio_listen_minutes", "k": "radio-city", "v": 999}))
        self.assertEqual(n({"e": "article_open", "k": "1234"}), ("article_open", "1234", 1))
        self.assertEqual(n({"e": "radio_listen_minutes", "k": "radio-city", "v": 5}), ("radio_listen_minutes", "radio-city", 5))

    def test_solo_contadores_agregados(self):
        cuerpo = json.dumps({"o": "web", "e": "article_open", "k": "77", "ip": "1.2.3.4", "email": "a@b.c"}).encode()
        medicion.procesar_cuerpo(self.almacen, cuerpo, "2026-10-09")
        medicion.procesar_cuerpo(self.almacen, cuerpo, "2026-10-09")
        lote = json.dumps({"o": "app", "eventos": [{"e": "app_open"}, {"e": "radio_play", "k": "lra22"}, {"e": "x"}]}).encode()
        self.assertEqual(medicion.procesar_cuerpo(self.almacen, lote, "2026-10-09"), 2)
        filas = [dict(f) for f in self.almacen.conn.execute("SELECT * FROM evento_diario")]
        self.assertEqual(set(filas[0]), {"fecha", "origen", "evento", "clave", "cantidad"})
        self.assertNotIn("1.2.3.4", json.dumps(filas))
        totales = self.almacen.totales("2026-10-09", "2026-10-09", "web")
        self.assertEqual(totales["article_open"]["por_clave"]["77"], 2)
        self.assertEqual(self.almacen.totales("2026-10-09", "2026-10-09", "app")["radio_play"]["total"], 1)

    def test_receptor_http(self):
        servidor = ThreadingHTTPServer(
            ("127.0.0.1", 0), medicion.crear_manejador(self.almacen, ("https://ledesmaparticipa.com.ar",))
        )
        hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
        hilo.start()
        self.addCleanup(servidor.server_close)
        self.addCleanup(servidor.shutdown)
        url = f"http://127.0.0.1:{servidor.server_address[1]}/e"
        pedido = urllib.request.Request(
            url, data=json.dumps({"o": "web", "e": "home_view"}).encode(),
            headers={"Content-Type": "text/plain", "Origin": "https://ledesmaparticipa.com.ar"}, method="POST",
        )
        with urllib.request.urlopen(pedido, timeout=5) as r:
            self.assertEqual(r.status, 204)
            self.assertEqual(r.headers.get("Access-Control-Allow-Origin"), "https://ledesmaparticipa.com.ar")
        pedido_ajeno = urllib.request.Request(
            url, data=b'{"o":"web","e":"home_view"}', headers={"Origin": "https://otro.test"}, method="POST"
        )
        with urllib.request.urlopen(pedido_ajeno, timeout=5) as r:
            self.assertIsNone(r.headers.get("Access-Control-Allow-Origin"))
        totales = self.almacen.totales("2000-01-01", "2999-12-31", "web")
        self.assertEqual(totales["home_view"]["total"], 2)

    def test_limite_de_frecuencia_en_memoria(self):
        limite = medicion.LimiteFrecuencia(maximo=2, ventana_segundos=60)
        self.assertTrue(limite.permitir("x"))
        self.assertTrue(limite.permitir("x"))
        self.assertFalse(limite.permitir("x"))


class TestRankingYAlertas(_ConDB):
    def _contenidos(self):
        filas = []
        for i, (terr, ig, fecha) in enumerate([
            ("local", 0, "2026-10-08"), ("nacional", 9, "2026-10-08"), ("departamental", 1, "2026-10-05"),
            ("provincial", 2, "2026-10-07"), ("nacional", 1, "2026-10-06"),
        ]):
            filas.append({"content_id": f"lp_x_{i}", "noticia_id": i + 1, "fecha": fecha, "hora": "09:00", "territorio": terr,
                          "categoria": None, "visual_format": "PHOTO_HEADLINE", "instagram_media_id": f"m{i}"})
        return filas

    def test_ranking_transparente_y_local_no_desaparece(self):
        contenidos = self._contenidos()
        interacciones = {f"m{i}": c for i, c in enumerate([0, 9, 1, 2, 1])}
        web = {"article_open": {"por_clave": {"1": 3}}}
        ranking = crecimiento.ranking_contenido(contenidos, interacciones, web, date(2026, 10, 9))
        self.assertEqual(len(ranking), 5)
        self.assertEqual(ranking[0]["content_id"], "lp_x_1")  # más interacción
        local = next(f for f in ranking if f["territorio"] == "local")
        self.assertGreater(local["puntaje"], 0)  # aperturas web + prioridad territorial

    def test_alerta_alcance_cero_frase_exacta(self):
        alertas = crecimiento.detectar_alertas([], {"a": 0, "b": 0, "c": 5}, [], {}, 0, None)
        frases = [a["detalle"] for a in alertas if a["tipo"] == "alcance_cero"]
        self.assertEqual(frases, [
            "Existen publicaciones con alcance 0. La causa técnica/editorial todavía no está determinada y debe medirse antes de atribuirla."
        ])

    def test_sin_alcance_no_se_evalua_ni_se_inventa(self):
        alertas = crecimiento.detectar_alertas([], {}, [], {}, 0, None)
        self.assertEqual([a["tipo"] for a in alertas], ["alcance_no_evaluable"])

    def test_interaccion_alta_y_caida_de_actividad(self):
        ranking = [{"content_id": f"c{i}", "interaccion_ig": v, "territorio": "nacional", "aperturas_web": 0}
                   for i, v in enumerate([0, 1, 0, 1, 0, 1, 40])]
        por_dia = {"2026-10-04": 12, "2026-10-05": 12, "2026-10-06": 12, "2026-10-07": 12, "2026-10-08": 3}
        tipos = [a["tipo"] for a in crecimiento.detectar_alertas(ranking, {}, [], por_dia, 0, None)]
        self.assertIn("interaccion_alta", tipos)
        self.assertIn("caida_actividad", tipos)

    def test_informe_completo_interno(self):
        n = self._guardar(hash_contenido="r1")
        self._publicar(n["id"], "2026-10-08", "09:00", "facebook", "fb_9")
        self._publicar(n["id"], "2026-10-08", "09:00", "instagram", "ig_9")
        snapshot = {"fecha": "2026-10-09",
                    "facebook": {"seguidores": metricas_meta.disponible(420, "x"), "alcance": metricas_meta.no_disponible("y")},
                    "instagram": {"seguidores": metricas_meta.disponible(147, "x")}}
        directorio = Path(self.tmp.name) / "metricas"
        shutil.copy(metricas_meta.DIRECTORIO_METRICAS / "baseline_2026-09-30.json", directorio.mkdir() or directorio)
        metricas_meta.guardar_snapshot({"fecha": "2026-10-02", "facebook": {"seguidores": metricas_meta.disponible(400, "x")},
                                        "instagram": {"seguidores": metricas_meta.disponible(140, "x")}}, directorio)
        almacen = medicion.AlmacenMedicion(Path(self.tmp.name) / "m.db")
        almacen.registrar("2026-10-08", "web", "article_open", str(n["id"]))
        almacen.registrar("2026-10-08", "web", "commercial_whatsapp_click", "dosis-jeans")
        almacen.registrar("2026-10-08", "web", "radio_play", "lra22")
        try:
            informe = crecimiento.generar_informe(self.db, date(2026, 10, 9), snapshot, almacen, directorio, medicion_activa=True)
        finally:
            almacen.close()
        self.assertTrue(informe["interno"])
        self.assertEqual(informe["facebook"]["seguidores"], 420)
        self.assertEqual(informe["facebook"]["variacion"], 20)
        self.assertEqual(informe["facebook"]["referencia_baseline_23_29_sep"], 321)
        self.assertEqual(informe["facebook"]["metricas"]["alcance"], metricas_meta.NO_DISPONIBLE)
        self.assertEqual(informe["instagram"]["variacion"], 7)
        self.assertEqual(informe["web"]["notas_abiertas_ayer"], 1)
        self.assertEqual(informe["web"]["guia_comercial"]["clics_whatsapp"], 1)
        self.assertEqual(informe["web"]["radios"]["play"], 1)
        self.assertEqual(informe["ranking"][0]["content_id"], "lp_20261008_0900_001")
        texto = crecimiento.informe_texto(informe)
        for seccion in ("CRECIMIENTO LEDESMA PARTICIPA", "FACEBOOK", "INSTAGRAM", "WEB", "APP", "RANKING INTERNO", "ALERTAS"):
            self.assertIn(seccion, texto)
        ruta = crecimiento.guardar_informe(informe, Path(self.tmp.name) / "informes")
        self.assertTrue(ruta.with_suffix(".txt").exists())
        self.assertEqual(crecimiento.ultimo_informe(Path(self.tmp.name) / "informes")["fecha"], "2026-10-09")

    def test_panel_muestra_crecimiento(self):
        from motor_noticias.panel.server import _crecimiento_html

        self.assertIn("Todavía no hay informe", _crecimiento_html({}))
        informe = {
            "fecha": "2026-10-09", "periodo": {"desde": "2026-10-02", "hasta": "2026-10-08"},
            "facebook": {"seguidores": 420, "variacion": 5, "variacion_desde": "2026-10-02", "metricas": {"alcance": "NO DISPONIBLE"},
                         "mejor_contenido": "NO DISPONIBLE"},
            "instagram": {"seguidores": 147, "variacion": "NO DISPONIBLE", "variacion_desde": None, "metricas": {}, "mejor_contenido": "NO DISPONIBLE"},
            "publicaciones": {"confirmadas_por_dia": {}, "por_formato": {}},
            "ranking": [], "alertas": [],
            "web": {"estado_medicion": "ACTIVA", "notas_abiertas_ayer": 0, "notas_abiertas_7d": 0, "visitas_portada_7d": 0,
                    "radios": {}, "guia_comercial": {}},
            "app": {"estado_medicion": "x", "eventos_7d": {}},
        }
        html = _crecimiento_html(informe)
        self.assertIn("Seguidores: <strong>420</strong>", html)
        self.assertIn("+5", html)


class TestSitioSEOyCTA(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "t.db"
        self.salida = Path(self.tmp.name) / "salida"
        _aislar(self, self.tmp.name)
        self.config = Path(self.tmp.name) / "sitio.json"
        self.config.write_text(json.dumps({
            "nombre": "Ledesma Participa", "descripcion": "d", "facebook_url": "https://www.facebook.com/1174992842373499",
            "instagram_url": "https://www.instagram.com/ledesmaparticipa/", "base_url_produccion": "https://ledesmaparticipa.com.ar",
            "medicion_endpoint": "https://medicion.ejemplo.test/e",
        }), encoding="utf-8")
        db = Database(self.db_path)
        db.guardar(_noticia(hash_contenido="s1"))
        db.guardar(_noticia(hash_contenido="s2", url_normalizada="https://ejemplo.test/2",
                            titulo_preparado="Inauguran una plaza en Libertador General San Martín",
                            titulo_original="Inauguran una plaza en Libertador General San Martín"))
        db.close()
        with patch("motor_noticias.sitio.generador.cargar_comercios", return_value=[]), \
                patch("motor_noticias.sitio.generador.cargar_videos", return_value=[]):
            generar_sitio(self.db_path, self.salida, base_url="https://ledesmaparticipa.com.ar", config_sitio_path=self.config)
        self.addCleanup(setattr, plantillas, "IMAGEN_OG_DEFAULT", None)

    def tearDown(self):
        self.tmp.cleanup()

    def _nota(self) -> str:
        (carpeta,) = [p for p in (self.salida / "noticias").iterdir() if "corte-de-agua" in p.name]
        return (carpeta / "index.html").read_text(encoding="utf-8")

    def test_news_article_y_open_graph(self):
        html = self._nota()
        ld = json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>', html).group(1))
        self.assertEqual(ld["@type"], "NewsArticle")
        for campo in ("headline", "datePublished", "dateModified", "author", "publisher", "mainEntityOfPage"):
            self.assertIn(campo, ld)
        self.assertEqual(ld["author"]["name"], "Ledesma Participa")  # sin autor falso
        self.assertNotIn("image", ld)  # la nota no tiene imagen propia: no se inventa
        for meta in ('property="og:title"', 'property="og:description"', 'property="og:image"', 'property="og:url"',
                     'name="twitter:card"', 'rel="canonical"', 'property="article:published_time"', 'rel="icon"'):
            self.assertIn(meta, html)

    def test_portada_con_og_image_sitemap_y_robots(self):
        index = (self.salida / "index.html").read_text(encoding="utf-8")
        self.assertIn('property="og:image" content="https://ledesmaparticipa.com.ar/assets/img/og-default-v2.png"', index)
        sitemap = (self.salida / "sitemap.xml").read_text(encoding="utf-8")
        self.assertRegex(sitemap, r"noticias/\d+-corte-de-agua[^<]*</loc><lastmod>2026-10-09</lastmod>")
        self.assertIn("Sitemap: https://ledesmaparticipa.com.ar/sitemap.xml", (self.salida / "robots.txt").read_text(encoding="utf-8"))

    def test_cta_seguir_y_medicion(self):
        html = self._nota()
        self.assertIn("Seguí Ledesma Participa", html)
        self.assertIn('data-ev="follow_cta_click" data-k="instagram"', html)
        self.assertIn('class="cabecera-seguir"', html)
        self.assertIn('assets/medicion.js" data-endpoint="https://medicion.ejemplo.test/e" data-pagina="article"', html)
        self.assertIn("También puede interesarte", html)
        self.assertTrue((self.salida / "assets" / "medicion.js").exists())
        self.assertEqual(json.loads((self.salida / "api" / "medicion.json").read_text(encoding="utf-8")),
                         {"endpoint": "https://medicion.ejemplo.test/e"})

    def test_sin_endpoint_no_hay_script_de_medicion(self):
        self.assertEqual(plantillas.script_medicion({}, "../"), "")


class TestRelacionadas(unittest.TestCase):
    def _n(self, i, **kw):
        from datetime import datetime, timezone

        base = {"id": i, "localidad": None, "territorio": "nacional", "categoria_tema": None, "es_informe": False,
                "fecha_orden": datetime(2026, 10, 1 + i, tzinfo=timezone.utc)}
        base.update(kw)
        return base

    def test_prioridad_localidad_territorio_categoria_reciente(self):
        actual = self._n(0, localidad="Calilegua", territorio="departamental", categoria_tema="salud")
        candidatas = [
            actual,
            self._n(1, territorio="nacional", categoria_tema="salud"),
            self._n(2, territorio="departamental"),
            self._n(3, localidad="Calilegua", territorio="departamental"),
            self._n(4, territorio="nacional"),
            self._n(5, es_informe=True, localidad="Calilegua"),
            self._n(6, territorio="departamental", categoria_tema="salud"),
        ]
        ids = [r["id"] for r in relacionadas_para(actual, candidatas, maximo=4)]
        self.assertEqual(ids, [3, 6, 2, 1])
        self.assertNotIn(0, ids)
        self.assertNotIn(5, ids)


class TestGuiaYRadios(unittest.TestCase):
    def test_eventos_guia_comercial(self):
        c = {"slug": "dosis-jeans", "nombre": "DOSIS", "whatsapp": "388", "whatsapp_url": "https://wa.me/549388",
             "instagram": "@dosis", "instagram_url": "https://www.instagram.com/dosis/", "promociones": ["2x1"],
             "contacto": {"url": "https://wa.me/549388", "etiqueta": "WhatsApp"}, "imagenes": []}
        ficha = plantillas.pagina_comercio(c=c, ruta_raiz="../../", config_sitio={"medicion_endpoint": "https://m.test/e"}, url_base="u")
        self.assertIn('data-ev="commercial_whatsapp_click" data-k="dosis-jeans"', ficha)
        self.assertIn('data-ev="commercial_instagram_click" data-k="dosis-jeans"', ficha)
        self.assertIn('data-pagina="commercial" data-clave="dosis-jeans"', ficha)
        self.assertIn("Espacio comercial", ficha)
        self.assertIn('data-ev="commercial_promo_open"', plantillas.tarjeta_comercio(c, ruta_raiz=""))

    def test_eventos_radios_en_reproductor(self):
        radio_js = (ASSETS / "radio.js").read_text(encoding="utf-8")
        for evento in ("radio_select", "radio_play", "radio_pause", "radio_listen_minutes"):
            self.assertIn(f'"{evento}"', radio_js)
            self.assertIn(evento, medicion.EVENTOS)

    @unittest.skipUnless(shutil.which("node"), "Node no disponible")
    def test_medicion_js_envia_solo_datos_agregados(self):
        script = r"""
        const enviados = [];
        global.Blob = class { constructor(p){ this.p = p.join(""); } };
        const atributos = {"data-endpoint": "https://m.test/e", "data-pagina": "article", "data-clave": "123"};
        let clic = null;
        global.document = { currentScript: { getAttribute: (k) => atributos[k] || null },
                            addEventListener: (t, f) => { clic = f; } };
        Object.defineProperty(globalThis, "navigator", { configurable: true,
          value: { sendBeacon: (url, blob) => { enviados.push(JSON.parse(blob.p)); return true; } } });
        require("vm").runInThisContext(require("fs").readFileSync(process.argv[1], "utf8"));
        const a = { getAttribute: (k) => ({ "data-ev": "follow_cta_click", "data-k": "instagram" })[k] || null };
        clic({ target: { closest: () => a } });
        LPMedicion.evento("article_open", "Juan Pérez");
        console.log(JSON.stringify(enviados));
        """
        salida = subprocess.run(["node", "-e", script, str(ASSETS / "medicion.js")], capture_output=True, text=True, timeout=30)
        self.assertEqual(salida.returncode, 0, salida.stderr)
        enviados = json.loads(salida.stdout)
        self.assertEqual(enviados[0], {"o": "web", "e": "article_open", "k": "123", "v": 1})
        self.assertEqual(enviados[1]["e"], "follow_cta_click")
        self.assertEqual(enviados[2]["k"], "")  # texto libre descartado
        for e in enviados:
            self.assertEqual(set(e), {"o", "e", "k", "v"})


if __name__ == "__main__":
    unittest.main()
