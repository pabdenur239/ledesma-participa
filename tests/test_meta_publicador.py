import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from motor_noticias.db import Database
from motor_noticias.dedupe import hash_contenido, normalizar_url
from motor_noticias.institucional import HORA_INSTITUCIONAL, reservar_franja_institucional
from motor_noticias.meta.cliente import ErrorClienteMeta, ResultadoFotoFacebook
from motor_noticias.meta.publicador import (
    MAX_INTENTOS_DEFAULT,
    _publicar_noticia_en_clave,
    publicar_franja,
    publicar_urgentes,
    reintentar_publicaciones,
)
from motor_noticias.models import Estado, Noticia

AHORA = datetime(2026, 8, 12, 12, 0, 0, tzinfo=timezone.utc)


class FakeClienteMeta:
    """Simulador de Meta para pruebas offline: nunca hace una petición de
    red real. Reproduce el flujo real de dos pasos (Facebook aloja la
    imagen -> Instagram reutiliza esa URL) para poder probar el flujo
    completo sin ningún hosting externo."""

    def __init__(
        self,
        fallar_facebook=False,
        fallar_instagram=False,
        fallar_obtener_url=False,
        fallar_verificacion=False,
        fallar_alojar_story=False,
        fallar_instagram_story=False,
        fallar_verificacion_story=False,
    ):
        self.fallar_facebook = fallar_facebook
        self.fallar_instagram = fallar_instagram
        self.fallar_obtener_url = fallar_obtener_url
        self.fallar_verificacion = fallar_verificacion
        self.fallar_alojar_story = fallar_alojar_story
        self.fallar_instagram_story = fallar_instagram_story
        self.fallar_verificacion_story = fallar_verificacion_story
        self.llamadas = []
        self._contador_fotos = 0
        self._contador_stories = 0

    def _nueva_foto(self):
        self._contador_fotos += 1
        return ResultadoFotoFacebook(photo_id=f"photo-{self._contador_fotos}", post_id=f"post-{self._contador_fotos}")

    def publicar_foto_facebook(self, contenido, ruta_imagen, dry_run=True):
        self.llamadas.append(("publicar_foto_facebook", str(ruta_imagen)))
        if self.fallar_facebook:
            raise ErrorClienteMeta("fallo simulado de Facebook")
        return self._nueva_foto()

    def publicar_foto_facebook_por_url(self, contenido, imagen_url, dry_run=True):
        self.llamadas.append(("publicar_foto_facebook_por_url", imagen_url))
        if self.fallar_facebook:
            raise ErrorClienteMeta("fallo simulado de Facebook")
        return self._nueva_foto()

    def publicar_comentario_facebook(self, post_id, texto, dry_run=True):
        self.llamadas.append(("publicar_comentario_facebook", post_id))
        return "comentario-fb-1"

    def verificar_publicacion(self, id_publicacion):
        self.llamadas.append(("verificar_publicacion", id_publicacion))
        if str(id_publicacion).startswith("media-story"):
            return not self.fallar_verificacion_story
        return not self.fallar_verificacion

    def obtener_url_publica_foto(self, photo_id):
        self.llamadas.append(("obtener_url_publica_foto", photo_id))
        if self.fallar_obtener_url:
            raise ErrorClienteMeta("Meta no devolvió una URL pública utilizable para la foto.")
        return f"https://scontent.fb.example/{photo_id}.jpg"

    def publicar_instagram(self, caption, imagen_url, dry_run=True):
        self.llamadas.append(("publicar_instagram", imagen_url))
        if self.fallar_instagram:
            raise ErrorClienteMeta("fallo simulado de Instagram")
        return "media-ig-456"

    def alojar_imagen_para_story(self, ruta_imagen, dry_run=True):
        self.llamadas.append(("alojar_imagen_para_story", str(ruta_imagen)))
        if self.fallar_alojar_story:
            raise ErrorClienteMeta("fallo simulado al alojar la imagen de la Story")
        self._contador_stories += 1
        return f"photo-story-{self._contador_stories}"

    def publicar_instagram_story(self, imagen_url, dry_run=True):
        self.llamadas.append(("publicar_instagram_story", imagen_url))
        if self.fallar_instagram_story:
            raise ErrorClienteMeta("fallo simulado de Instagram Story")
        return f"media-story-{self._contador_stories}"


def _noticia(db, n=1, **overrides):
    base = dict(
        id=None,
        titulo_original="Título",
        texto_original="Texto de la noticia con contenido suficiente para reseña.",
        url_fuente=f"http://a.com/{n}",
        nombre_fuente="Prensa Jujuy",
        fecha_fuente="",
        fecha_recoleccion=AHORA.isoformat(),
        estado=Estado.PREPARADA.value,
        hash_contenido="",
        territorio="local",
        titulo_preparado="Título",
        texto_preparado="Texto de la noticia con contenido suficiente para reseña.",
    )
    base.update(overrides)
    url = base["url_fuente"]
    base["url_normalizada"] = normalizar_url(url)
    base["hash_contenido"] = hash_contenido(base["titulo_original"], base["texto_original"] + url)
    noticia = Noticia(**base)
    db.guardar(noticia)
    return noticia


class BaseTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmpdir.name) / "test.db")

    def tearDown(self):
        self.db.close()
        self.tmpdir.cleanup()


class TestPublicarFranja(BaseTest):
    def test_sin_contenido_en_la_franja(self):
        resultado = publicar_franja(self.db, "2026-08-12", "09:30", ahora=AHORA)
        self.assertEqual(resultado.resultado, "sin_contenido")

    def test_noticia_pendiente_de_revision_no_se_publica(self):
        n = _noticia(self.db, requiere_revision_especial=True, categoria_riesgo="judicial")
        self.db.guardar_agenda_item("2026-08-12", "09:30", "normal", "local", n.id, AHORA.isoformat())

        resultado = publicar_franja(self.db, "2026-08-12", "09:30", ahora=AHORA)

        self.assertEqual(resultado.resultado, "pendiente_revision_humana")

    def test_flujo_completo_facebook_primero_instagram_reutiliza_su_cdn(self):
        n = _noticia(self.db)
        self.db.guardar_agenda_item("2026-08-12", "09:30", "normal", "local", n.id, AHORA.isoformat())
        fake = FakeClienteMeta()

        resultado = publicar_franja(self.db, "2026-08-12", "09:30", cliente_fb=fake, cliente_ig=fake, ahora=AHORA)

        self.assertEqual(resultado.resultado, "procesada")
        estados = {r.red_social: r.estado for r in resultado.redes}
        self.assertEqual(
            estados, {"facebook": "publicado", "instagram": "publicado", "instagram_story": "publicado"}
        )

        # Facebook se publica antes de que se consulte su URL pública, y esa
        # URL (la de Facebook, no un hosting propio) es la que usa Instagram.
        nombres_llamadas = [l[0] for l in fake.llamadas]
        self.assertLess(
            nombres_llamadas.index("publicar_foto_facebook"), nombres_llamadas.index("obtener_url_publica_foto")
        )
        self.assertLess(
            nombres_llamadas.index("obtener_url_publica_foto"), nombres_llamadas.index("publicar_instagram")
        )
        # la URL con la que se llamó a Instagram viene de obtener_url_publica_foto
        llamada_ig = [v for n, v in fake.llamadas if n == "publicar_instagram"][0]
        self.assertIn("scontent.fb.example", llamada_ig)

        fila_fb = self.db.obtener_programacion_meta("2026-08-12", "09:30", "facebook")
        fila_ig = self.db.obtener_programacion_meta("2026-08-12", "09:30", "instagram")
        self.assertEqual(fila_fb["meta_id"], "post-1")
        self.assertEqual(fila_fb["referencia_extra"], "photo-1")
        self.assertEqual(fila_ig["meta_id"], "media-ig-456")
        self.assertEqual(self.db.obtener(n.id)["estado"], Estado.PUBLICADA.value)

    def test_nunca_usa_ni_intenta_el_primer_comentario(self):
        n = _noticia(self.db)
        self.db.guardar_agenda_item("2026-08-12", "09:30", "normal", "local", n.id, AHORA.isoformat())
        fake = FakeClienteMeta()

        resultado = publicar_franja(self.db, "2026-08-12", "09:30", cliente_fb=fake, cliente_ig=fake, ahora=AHORA)

        estados = {r.red_social: r.estado for r in resultado.redes}
        self.assertEqual(estados["facebook"], "publicado")
        self.assertFalse(any(n == "publicar_comentario_facebook" for n, _ in fake.llamadas))
        self.assertEqual(self.db.obtener(n.id)["estado"], Estado.PUBLICADA.value)

    def test_verificacion_fallida_no_marca_publicado_y_no_duplica_en_reintento(self):
        n = _noticia(self.db)
        self.db.guardar_agenda_item("2026-08-12", "09:30", "normal", "local", n.id, AHORA.isoformat())
        fake_falla_verificacion = FakeClienteMeta(fallar_verificacion=True)

        resultado = publicar_franja(
            self.db, "2026-08-12", "09:30",
            cliente_fb=fake_falla_verificacion, cliente_ig=fake_falla_verificacion, ahora=AHORA,
        )
        estados = {r.red_social: r.estado for r in resultado.redes}
        self.assertEqual(estados["facebook"], "error")
        fila_fb = self.db.obtener_programacion_meta("2026-08-12", "09:30", "facebook")
        self.assertEqual(fila_fb["meta_id"], "post-1")  # se conserva: ya lo publicó Meta

        # Reintento con verificación ahora exitosa: nunca vuelve a publicar
        # (mismo post-1), solo confirma y recién ahí marca "publicado".
        fake_ok = FakeClienteMeta()
        resultado_reintento = publicar_franja(
            self.db, "2026-08-12", "09:30", cliente_fb=fake_ok, cliente_ig=fake_ok, ahora=AHORA
        )
        estados_reintento = {r.red_social: r.estado for r in resultado_reintento.redes}
        self.assertEqual(estados_reintento["facebook"], "publicado")
        self.assertEqual(
            [r.meta_id for r in resultado_reintento.redes if r.red_social == "facebook"][0], "post-1"
        )
        self.assertFalse(
            any(nombre in ("publicar_foto_facebook", "publicar_foto_facebook_por_url") for nombre, _ in fake_ok.llamadas)
        )
        self.assertIn(("verificar_publicacion", "post-1"), fake_ok.llamadas)

    def test_si_facebook_falla_instagram_no_se_intenta(self):
        n = _noticia(self.db)
        self.db.guardar_agenda_item("2026-08-12", "09:30", "normal", "local", n.id, AHORA.isoformat())
        fake = FakeClienteMeta(fallar_facebook=True)

        resultado = publicar_franja(self.db, "2026-08-12", "09:30", cliente_fb=fake, cliente_ig=fake, ahora=AHORA)

        estados = {r.red_social: r.estado for r in resultado.redes}
        self.assertEqual(estados["facebook"], "error")
        self.assertEqual(estados["instagram"], "omitido")
        self.assertFalse(any(n == "publicar_instagram" for n, _ in fake.llamadas))
        # obtener_url_publica_foto sí se llama para la Story (independiente
        # del feed), pero nunca con la foto del feed de Facebook (que ni
        # siquiera llegó a crearse, porque Facebook falló).
        self.assertFalse(any(n == "obtener_url_publica_foto" and v == "photo-1" for n, v in fake.llamadas))

        fila_ig = self.db.obtener_programacion_meta("2026-08-12", "09:30", "instagram")
        self.assertEqual(fila_ig["estado"], "pendiente")  # nunca se tocó

    def test_si_meta_no_da_url_apta_para_instagram_se_reporta_el_bloqueo(self):
        n = _noticia(self.db)
        self.db.guardar_agenda_item("2026-08-12", "09:30", "normal", "local", n.id, AHORA.isoformat())
        fake = FakeClienteMeta(fallar_obtener_url=True)

        resultado = publicar_franja(self.db, "2026-08-12", "09:30", cliente_fb=fake, cliente_ig=fake, ahora=AHORA)

        estados = {r.red_social: r.estado for r in resultado.redes}
        self.assertEqual(estados["facebook"], "publicado")
        self.assertEqual(estados["instagram"], "error")
        fila_ig = self.db.obtener_programacion_meta("2026-08-12", "09:30", "instagram")
        self.assertIn("URL pública", fila_ig["ultimo_error"])
        self.assertFalse(any(n == "publicar_instagram" for n, _ in fake.llamadas))

    def test_idempotencia_no_vuelve_a_publicar_una_franja_ya_publicada(self):
        n = _noticia(self.db)
        self.db.guardar_agenda_item("2026-08-12", "09:30", "normal", "local", n.id, AHORA.isoformat())
        fake = FakeClienteMeta()

        publicar_franja(self.db, "2026-08-12", "09:30", cliente_fb=fake, cliente_ig=fake, ahora=AHORA)
        llamadas_primera_vez = len(fake.llamadas)
        resultado = publicar_franja(self.db, "2026-08-12", "09:30", cliente_fb=fake, cliente_ig=fake, ahora=AHORA)

        estados = {r.red_social: r.estado for r in resultado.redes}
        self.assertEqual(
            estados, {"facebook": "omitido", "instagram": "omitido", "instagram_story": "omitido"}
        )
        self.assertEqual(len(fake.llamadas), llamadas_primera_vez)  # ninguna llamada nueva

    def test_reintento_de_instagram_reutiliza_el_photo_id_sin_resubir_a_facebook(self):
        n = _noticia(self.db)
        self.db.guardar_agenda_item("2026-08-12", "09:30", "normal", "local", n.id, AHORA.isoformat())
        fake_falla_ig = FakeClienteMeta(fallar_instagram=True)
        publicar_franja(self.db, "2026-08-12", "09:30", cliente_fb=fake_falla_ig, cliente_ig=fake_falla_ig, ahora=AHORA)

        fake_ok = FakeClienteMeta()
        resultado = publicar_franja(self.db, "2026-08-12", "09:30", cliente_fb=fake_ok, cliente_ig=fake_ok, ahora=AHORA)

        estados = {r.red_social: r.estado for r in resultado.redes}
        self.assertEqual(estados["facebook"], "omitido")  # no se resube
        self.assertEqual(estados["instagram"], "publicado")
        self.assertFalse(any(n in ("publicar_foto_facebook", "publicar_foto_facebook_por_url") for n, _ in fake_ok.llamadas))
        # reutiliza el photo_id ya persistido (photo-1) para pedir la URL de nuevo
        self.assertIn(("obtener_url_publica_foto", "photo-1"), fake_ok.llamadas)


class TestReintentarPublicaciones(BaseTest):
    def test_reintenta_solo_la_red_que_fallo(self):
        n = _noticia(self.db)
        self.db.guardar_agenda_item("2026-08-12", "09:30", "normal", "local", n.id, AHORA.isoformat())
        fake_falla = FakeClienteMeta(fallar_instagram=True)
        publicar_franja(self.db, "2026-08-12", "09:30", cliente_fb=fake_falla, cliente_ig=fake_falla, ahora=AHORA)

        fake_ok = FakeClienteMeta()
        resultados = reintentar_publicaciones(self.db, cliente_fb=fake_ok, cliente_ig=fake_ok, ahora=AHORA)

        self.assertEqual(len(resultados), 1)
        estados = {r.red_social: r.estado for r in resultados[0].redes}
        self.assertEqual(estados["facebook"], "omitido")  # ya estaba publicado, no se repite
        self.assertEqual(estados["instagram"], "publicado")

    def test_no_reintenta_mas_alla_del_maximo_de_intentos(self):
        n = _noticia(self.db)
        self.db.guardar_agenda_item("2026-08-12", "09:30", "normal", "local", n.id, AHORA.isoformat())
        fake_falla = FakeClienteMeta(fallar_facebook=True)

        for _ in range(3):
            publicar_franja(self.db, "2026-08-12", "09:30", cliente_fb=fake_falla, cliente_ig=fake_falla, ahora=AHORA)

        pendientes = self.db.listar_programacion_meta_para_reintentar(max_intentos=3)
        self.assertEqual(pendientes, [])  # ya alcanzaron el máximo, no se reintentan más

    def test_facebook_que_nunca_publica_deja_instagram_sin_intentar_para_siempre(self):
        n = _noticia(self.db)
        self.db.guardar_agenda_item("2026-08-12", "09:30", "normal", "local", n.id, AHORA.isoformat())
        fake_falla = FakeClienteMeta(fallar_facebook=True)

        for _ in range(3):
            publicar_franja(self.db, "2026-08-12", "09:30", cliente_fb=fake_falla, cliente_ig=fake_falla, ahora=AHORA)

        fila_ig = self.db.obtener_programacion_meta("2026-08-12", "09:30", "instagram")
        self.assertEqual(fila_ig["estado"], "pendiente")
        self.assertEqual(fila_ig["intentos"], 0)

    def test_publicar_urgentes_deja_de_reintentar_una_red_tras_el_tope(self):
        # Bug real corregido 21/8: a diferencia de reintentar_publicaciones
        # (capado por listar_programacion_meta_para_reintentar), publicar_
        # urgentes llamaba a _publicar_noticia_en_clave en cada corrida de
        # MetaUrgentes (cada 15 min, sin límite) mientras la urgente no
        # tuviera Facebook+Instagram publicados — una fila real llegó a 68
        # intentos en producción, machacando la Graph API sin freno.
        n = _noticia(self.db)
        agenda_id = self.db.guardar_agenda_item("2026-08-12", None, "urgente", "local", n.id, AHORA.isoformat())
        fake = FakeClienteMeta(fallar_instagram=True)

        # Simula MAX_INTENTOS_DEFAULT + varias corridas más de MetaUrgentes.
        for _ in range(MAX_INTENTOS_DEFAULT + 5):
            publicar_urgentes(self.db, "2026-08-12", cliente_fb=fake, cliente_ig=fake, ahora=AHORA)

        fila_ig = self.db.obtener_programacion_meta("2026-08-12", f"urgente-{agenda_id}", "instagram")
        self.assertEqual(fila_ig["estado"], "error")
        self.assertEqual(fila_ig["intentos"], MAX_INTENTOS_DEFAULT)  # nunca supera el tope
        llamadas_instagram = [l for l in fake.llamadas if l[0] == "publicar_instagram"]
        self.assertEqual(len(llamadas_instagram), MAX_INTENTOS_DEFAULT)  # ninguna llamada de más a Meta


class TestDeduplicacionEntreCircuitos(BaseTest):
    """El gate de deduplicación de `_publicar_noticia_en_clave` es único y
    común a los tres circuitos (franja fija, urgente y reintento): estos
    tests cubren específicamente que la misma noticia (o su equivalente por
    otra fuente) no salga publicada dos veces cuando entra por circuitos
    distintos, aunque sea un registro interno (`noticia_id`) distinto."""

    def test_bloquea_la_misma_noticia_publicada_por_normal_y_por_urgente(self):
        # Mismo caso real detectado en producción: dos fuentes distintas
        # cubren el mismo partido, con título apenas distinto (sin URL ni
        # hash_contenido en común) — depende del fingerprint de contenido.
        a = _noticia(
            self.db, 1,
            titulo_original="Independiente Rivadavia apuesta por sorprender como local a un Fluminense sin entrenador",
            titulo_preparado="Independiente Rivadavia apuesta por sorprender como local a un Fluminense sin entrenador",
        )
        b = _noticia(
            self.db, 2,
            titulo_original="Independiente Rivadavia busca hacer historia ante Fluminense en la Copa Libertadores",
            titulo_preparado="Independiente Rivadavia busca hacer historia ante Fluminense en la Copa Libertadores",
        )
        self.db.guardar_agenda_item("2026-08-12", "09:30", "normal", "local", a.id, AHORA.isoformat())
        self.db.guardar_agenda_item("2026-08-12", None, "urgente", "local", b.id, AHORA.isoformat())

        fake = FakeClienteMeta()
        resultado_normal = publicar_franja(
            self.db, "2026-08-12", "09:30", cliente_fb=fake, cliente_ig=fake, ahora=AHORA
        )
        self.assertEqual(resultado_normal.resultado, "procesada")
        llamadas_antes = len(fake.llamadas)

        resultados_urgentes = publicar_urgentes(
            self.db, "2026-08-12", cliente_fb=fake, cliente_ig=fake, ahora=AHORA
        )
        self.assertEqual(len(resultados_urgentes), 1)
        self.assertEqual(resultados_urgentes[0].resultado, "duplicado_bloqueado")
        self.assertEqual(len(fake.llamadas), llamadas_antes)  # ninguna llamada nueva a Meta

    def test_bloquea_al_reintentar_una_urgente_si_otra_urgente_ya_la_publico(self):
        # B entra primero y falla por un motivo ajeno a duplicados (error de
        # red simulado). Mientras tanto A -su misma noticia, otro registro-
        # se publica por el circuito de urgentes. El reintento de B (circuito
        # de MetaReintentos) debe bloquearla por duplicado, no reintentar
        # contra Meta de nuevo.
        b = _noticia(
            self.db, 1,
            titulo_original="Independiente Rivadavia apuesta por sorprender como local a un Fluminense sin entrenador",
            titulo_preparado="Independiente Rivadavia apuesta por sorprender como local a un Fluminense sin entrenador",
        )
        self.db.guardar_agenda_item("2026-08-12", None, "urgente", "local", b.id, AHORA.isoformat())
        fake_falla = FakeClienteMeta(fallar_facebook=True)
        publicar_urgentes(self.db, "2026-08-12", cliente_fb=fake_falla, cliente_ig=fake_falla, ahora=AHORA)

        agenda_b = [item for item in self.db.listar_agenda("2026-08-12") if item["noticia_id"] == b.id][0]
        clave_b = f"urgente-{agenda_b['id']}"
        self.assertEqual(self.db.obtener_programacion_meta("2026-08-12", clave_b, "facebook")["estado"], "error")

        a = _noticia(
            self.db, 2,
            titulo_original="Independiente Rivadavia busca hacer historia ante Fluminense en la Copa Libertadores",
            titulo_preparado="Independiente Rivadavia busca hacer historia ante Fluminense en la Copa Libertadores",
        )
        agenda_a_id = self.db.guardar_agenda_item(
            "2026-08-12", None, "urgente", "local", a.id, AHORA.isoformat()
        )
        # Se publica A de forma aislada (sin volver a barrer la cola de
        # urgentes, que reintentaría a B primero al ser la más vieja):
        # mismo helper interno que usan publicar_franja/publicar_urgentes.
        fake_ok = FakeClienteMeta()
        resultado_a = _publicar_noticia_en_clave(
            self.db, "2026-08-12", f"urgente-{agenda_a_id}", a.id, fake_ok, fake_ok, AHORA
        )
        self.assertEqual(resultado_a.resultado, "procesada")
        self.assertEqual(self.db.obtener(a.id)["estado"], Estado.PUBLICADA.value)

        fake_reintentos = FakeClienteMeta()
        resultados_reintento = reintentar_publicaciones(
            self.db, cliente_fb=fake_reintentos, cliente_ig=fake_reintentos, ahora=AHORA
        )
        resultado_b = [r for r in resultados_reintento if r.noticia_id == b.id][0]
        self.assertEqual(resultado_b.resultado, "duplicado_bloqueado")
        self.assertEqual(fake_reintentos.llamadas, [])  # nunca llegó a tocar a Meta

        fila_fb_b = self.db.obtener_programacion_meta("2026-08-12", clave_b, "facebook")
        self.assertEqual(fila_fb_b["estado"], "duplicado")
        # Una vez bloqueada por duplicado, no vuelve a aparecer como
        # pendiente de reintento (no queda en 'error' dando vueltas).
        pendientes = self.db.listar_programacion_meta_para_reintentar(max_intentos=10)
        self.assertFalse(any(p["hora"] == clave_b for p in pendientes))

    def test_bloquea_por_misma_url_normalizada_aunque_los_ids_internos_sean_distintos(self):
        # Señal más fuerte que el fingerprint de contenido: misma URL
        # normalizada, títulos completamente distintos entre sí.
        misma_url = "https://ejemplo.test/nota/inundacion-en-libertador"
        a = _noticia(self.db, 1, url_fuente=misma_url, titulo_original="Título A", titulo_preparado="Título A")
        b = _noticia(self.db, 2, url_fuente=misma_url, titulo_original="Un título completamente diferente", titulo_preparado="Un título completamente diferente")
        self.assertEqual(a.url_normalizada, b.url_normalizada)

        self.db.guardar_agenda_item("2026-08-12", "09:30", "normal", "local", a.id, AHORA.isoformat())
        self.db.guardar_agenda_item("2026-08-12", "10:00", "normal", "local", b.id, AHORA.isoformat())

        fake = FakeClienteMeta()
        publicar_franja(self.db, "2026-08-12", "09:30", cliente_fb=fake, cliente_ig=fake, ahora=AHORA)
        llamadas_antes = len(fake.llamadas)

        resultado_b = publicar_franja(self.db, "2026-08-12", "10:00", cliente_fb=fake, cliente_ig=fake, ahora=AHORA)

        self.assertEqual(resultado_b.resultado, "duplicado_bloqueado")
        self.assertEqual(len(fake.llamadas), llamadas_antes)

    def test_misma_noticia_id_asignada_a_dos_franjas_no_sale_publicada_dos_veces(self):
        # Bug real corregido: si la MISMA noticia_id termina asignada a dos
        # agenda_item distintos (dos franjas normales, o una franja y una
        # urgente — no importa el mecanismo por el que haya ocurrido: una
        # regeneración de agenda concurrente, un selector alternativo,
        # etc.), la segunda franja no debe volver a publicarla de verdad.
        # Antes, el gate de duplicados solo miraba noticias con OTRO id
        # (fingerprint de contenido) y se saltaba por completo cuando
        # noticia["estado"] ya era "publicada" — exactamente la situación
        # de la segunda franja — así que el segundo POST pasaba derecho.
        n = _noticia(self.db)
        self.db.guardar_agenda_item("2026-08-12", "09:30", "normal", "local", n.id, AHORA.isoformat())
        self.db.guardar_agenda_item("2026-08-12", "10:00", "normal", "local", n.id, AHORA.isoformat())
        fake = FakeClienteMeta()

        resultado_1 = publicar_franja(self.db, "2026-08-12", "09:30", cliente_fb=fake, cliente_ig=fake, ahora=AHORA)
        self.assertEqual(resultado_1.resultado, "procesada")
        estados_1 = {r.red_social: r.estado for r in resultado_1.redes}
        self.assertEqual(estados_1["facebook"], "publicado")
        self.assertEqual(estados_1["instagram"], "publicado")
        llamadas_antes = len(fake.llamadas)

        resultado_2 = publicar_franja(self.db, "2026-08-12", "10:00", cliente_fb=fake, cliente_ig=fake, ahora=AHORA)

        self.assertEqual(resultado_2.resultado, "duplicado_bloqueado")
        self.assertEqual(len(fake.llamadas), llamadas_antes)  # ningún POST nuevo a Meta

        fila_fb_10 = self.db.obtener_programacion_meta("2026-08-12", "10:00", "facebook")
        self.assertEqual(fila_fb_10["estado"], "duplicado")
        self.assertIn(f"noticia #{n.id}", fila_fb_10["ultimo_error"])
        # la fila de las 09:30 (la que sí publicó de verdad) queda intacta
        fila_fb_9 = self.db.obtener_programacion_meta("2026-08-12", "09:30", "facebook")
        self.assertEqual(fila_fb_9["estado"], "publicado")

    def test_misma_noticia_id_normal_y_urgente_no_sale_publicada_dos_veces(self):
        # Misma situación que arriba, pero con las dos claves reales que
        # usa el sistema para franja fija y urgente ("HH:MM" vs
        # "urgente-<id>"), no dos franjas fijas.
        n = _noticia(self.db)
        self.db.guardar_agenda_item("2026-08-12", "09:30", "normal", "local", n.id, AHORA.isoformat())
        agenda_urgente_id = self.db.guardar_agenda_item(
            "2026-08-12", None, "urgente", "local", n.id, AHORA.isoformat()
        )
        fake = FakeClienteMeta()

        publicar_franja(self.db, "2026-08-12", "09:30", cliente_fb=fake, cliente_ig=fake, ahora=AHORA)
        llamadas_antes = len(fake.llamadas)

        resultados_urgentes = publicar_urgentes(self.db, "2026-08-12", cliente_fb=fake, cliente_ig=fake, ahora=AHORA)

        self.assertEqual(len(resultados_urgentes), 1)
        self.assertEqual(resultados_urgentes[0].resultado, "duplicado_bloqueado")
        self.assertEqual(len(fake.llamadas), llamadas_antes)
        clave_urgente = f"urgente-{agenda_urgente_id}"
        fila_urgente = self.db.obtener_programacion_meta("2026-08-12", clave_urgente, "facebook")
        self.assertEqual(fila_urgente["estado"], "duplicado")

    def test_no_bloquea_noticias_distintas_que_comparten_solo_una_palabra_de_lugar(self):
        # Control negativo: no cualquier coincidencia dispara el bloqueo.
        a = _noticia(
            self.db, 1,
            titulo_original="La Catedral de Jujuy celebrará el Día del Niño en Plaza Belgrano",
            titulo_preparado="La Catedral de Jujuy celebrará el Día del Niño en Plaza Belgrano",
        )
        b = _noticia(
            self.db, 2,
            titulo_original="Recuperaron 39 celulares durante un operativo de seguridad en Jujuy",
            titulo_preparado="Recuperaron 39 celulares durante un operativo de seguridad en Jujuy",
        )
        self.db.guardar_agenda_item("2026-08-12", "09:30", "normal", "local", a.id, AHORA.isoformat())
        self.db.guardar_agenda_item("2026-08-12", "10:00", "normal", "local", b.id, AHORA.isoformat())

        fake = FakeClienteMeta()
        publicar_franja(self.db, "2026-08-12", "09:30", cliente_fb=fake, cliente_ig=fake, ahora=AHORA)
        resultado_b = publicar_franja(self.db, "2026-08-12", "10:00", cliente_fb=fake, cliente_ig=fake, ahora=AHORA)

        self.assertEqual(resultado_b.resultado, "procesada")
        estados = {r.red_social: r.estado for r in resultado_b.redes}
        self.assertEqual(
            estados, {"facebook": "publicado", "instagram": "publicado", "instagram_story": "publicado"}
        )

    def test_bloquea_por_cuerpo_cuando_titulos_de_fuentes_distintas_no_comparten_palabras(self):
        # Caso real detectado en producción 20/8: Infobae y La Nación sobre
        # el mismo partido Flamengo-Cruzeiro, titulados desde ángulos tan
        # distintos (jugadores vs. equipos) que los títulos no comparten
        # ninguna palabra relevante — el fingerprint de solo-título no
        # alcanzaba y las dos salieron publicadas. Ahora, entre fuentes
        # distintas, el gate también compara título+cuerpo.
        a = _noticia(
            self.db, 1,
            nombre_fuente="Infobae",
            titulo_original="2-1. Dos maravillas de Arrascaeta y Lino llevan a Flamengo a cuartos de final",
            titulo_preparado="2-1. Dos maravillas de Arrascaeta y Lino llevan a Flamengo a cuartos de final",
            texto_original=(
                "El campeón Flamengo se impuso por 2-1 a Cruzeiro este miércoles en el "
                "Maracaná de Río de Janeiro y avanzó a los cuartos de final de la Copa "
                "Libertadores con dos golazos de Giorgian de Arrascaeta y Samuel Lino."
            ),
        )
        b = _noticia(
            self.db, 2,
            nombre_fuente="La Nación",
            titulo_original="Flamengo le ganó a Cruzeiro 2-1 y lo eliminó de la Copa Libertadores con un show de golazos en el Maracaná",
            titulo_preparado="Flamengo le ganó a Cruzeiro 2-1 y lo eliminó de la Copa Libertadores con un show de golazos en el Maracaná",
            texto_original=(
                "El conjunto de Rio de Janeiro se aseguró el pase a cuartos de la mano "
                "de De Arrascaeta y Samuel Lino, mientras que el argentino Lucas Romero "
                "anotó para los visitantes."
            ),
        )
        self.db.guardar_agenda_item("2026-08-12", "09:30", "normal", "local", a.id, AHORA.isoformat())
        self.db.guardar_agenda_item("2026-08-12", "10:00", "normal", "local", b.id, AHORA.isoformat())

        fake = FakeClienteMeta()
        publicar_franja(self.db, "2026-08-12", "09:30", cliente_fb=fake, cliente_ig=fake, ahora=AHORA)
        llamadas_antes = len(fake.llamadas)

        resultado_b = publicar_franja(self.db, "2026-08-12", "10:00", cliente_fb=fake, cliente_ig=fake, ahora=AHORA)

        self.assertEqual(resultado_b.resultado, "duplicado_bloqueado")
        self.assertEqual(len(fake.llamadas), llamadas_antes)  # ningún POST nuevo a Meta

    def test_no_bloquea_anuncios_distintos_de_la_misma_fuente_con_lenguaje_de_tramite_parecido(self):
        # Control negativo del caso anterior: dos anuncios oficiales reales
        # y distintos de la MISMA fuente comparten tanto lenguaje de trámite
        # ("Ministerio de Desarrollo Humano... a través de la
        # Secretaría... jueves 20 de agosto") que comparar por cuerpo
        # completo los marcaría como duplicado si se aplicara entre
        # cualquier par de noticias — por eso la comparación por cuerpo solo
        # se activa entre fuentes distintas (ver test anterior), nunca
        # dentro de la misma fuente.
        a = _noticia(
            self.db, 1,
            nombre_fuente="Jujuy al día",
            titulo_original="Hoy en Lozano la Oficina Móvil para Personas con Discapacidad",
            titulo_preparado="Hoy en Lozano la Oficina Móvil para Personas con Discapacidad",
            texto_original=(
                "El dispositivo estará el jueves 20 de agosto. El Ministerio de "
                "Desarrollo Humano de Jujuy, a través de la Dirección Provincial de "
                "Inclusión de Personas con Discapacidad, que depende de la Secretaría "
                "de Desarrollo Integral."
            ),
        )
        b = _noticia(
            self.db, 2,
            nombre_fuente="Jujuy al día",
            titulo_original="Familias de localidades puneñas recibirán unidades alimentarias",
            titulo_preparado="Familias de localidades puneñas recibirán unidades alimentarias",
            texto_original=(
                "El operativo de entrega de unidades alimentarias iniciará este jueves "
                "20 de agosto para familias de Abra Pampa, Tres Cruces y Cusi Cusi. El "
                "Ministerio de Desarrollo Humano, a través de la Secretaría de "
                "Asistencia Directa, comunica que desde el jueves 20."
            ),
        )
        self.db.guardar_agenda_item("2026-08-12", "09:30", "normal", "local", a.id, AHORA.isoformat())
        self.db.guardar_agenda_item("2026-08-12", "10:00", "normal", "local", b.id, AHORA.isoformat())

        fake = FakeClienteMeta()
        publicar_franja(self.db, "2026-08-12", "09:30", cliente_fb=fake, cliente_ig=fake, ahora=AHORA)
        resultado_b = publicar_franja(self.db, "2026-08-12", "10:00", cliente_fb=fake, cliente_ig=fake, ahora=AHORA)

        self.assertEqual(resultado_b.resultado, "procesada")
        estados = {r.red_social: r.estado for r in resultado_b.redes}
        self.assertEqual(estados["facebook"], "publicado")


class TestPublicarStoryInstagram(BaseTest):
    """Cobertura de la Instagram Story como paso adicional, independiente
    del feed, dentro de `_publicar_noticia_en_clave` — mismos tres circuitos
    (franja fija, urgente, reintento) porque los tres pasan por ahí."""

    def test_publica_la_story_junto_con_el_feed(self):
        n = _noticia(self.db)
        self.db.guardar_agenda_item("2026-08-12", "09:30", "normal", "local", n.id, AHORA.isoformat())
        fake = FakeClienteMeta()

        resultado = publicar_franja(self.db, "2026-08-12", "09:30", cliente_fb=fake, cliente_ig=fake, ahora=AHORA)

        estados = {r.red_social: r.estado for r in resultado.redes}
        self.assertEqual(estados["instagram_story"], "publicado")
        fila_story = self.db.obtener_programacion_meta("2026-08-12", "09:30", "instagram_story")
        self.assertIsNotNone(fila_story["meta_id"])
        self.assertIsNotNone(fila_story["publicada_en"])

    def test_nunca_genera_una_fila_de_facebook_story_no_existe_ese_circuito(self):
        n = _noticia(self.db)
        self.db.guardar_agenda_item("2026-08-12", "09:30", "normal", "local", n.id, AHORA.isoformat())
        fake = FakeClienteMeta()

        publicar_franja(self.db, "2026-08-12", "09:30", cliente_fb=fake, cliente_ig=fake, ahora=AHORA)

        filas = self.db.listar_programacion_meta("2026-08-12")
        redes = {f["red_social"] for f in filas}
        self.assertEqual(redes, {"facebook", "instagram", "instagram_story"})

    def test_story_se_publica_aunque_el_feed_de_facebook_falle(self):
        # Regla explícita: la Story no depende de que el feed haya publicado.
        n = _noticia(self.db)
        self.db.guardar_agenda_item("2026-08-12", "09:30", "normal", "local", n.id, AHORA.isoformat())
        fake = FakeClienteMeta(fallar_facebook=True)

        resultado = publicar_franja(self.db, "2026-08-12", "09:30", cliente_fb=fake, cliente_ig=fake, ahora=AHORA)

        estados = {r.red_social: r.estado for r in resultado.redes}
        self.assertEqual(estados["facebook"], "error")
        self.assertEqual(estados["instagram_story"], "publicado")

    def test_error_de_meta_en_la_story_no_marca_publicado(self):
        n = _noticia(self.db)
        self.db.guardar_agenda_item("2026-08-12", "09:30", "normal", "local", n.id, AHORA.isoformat())
        fake = FakeClienteMeta(fallar_instagram_story=True)

        resultado = publicar_franja(self.db, "2026-08-12", "09:30", cliente_fb=fake, cliente_ig=fake, ahora=AHORA)

        estados = {r.red_social: r.estado for r in resultado.redes}
        self.assertEqual(estados["instagram_story"], "error")
        fila_story = self.db.obtener_programacion_meta("2026-08-12", "09:30", "instagram_story")
        self.assertIsNone(fila_story["meta_id"])

    def test_verificacion_fallida_de_story_no_marca_publicado_y_reintento_no_duplica(self):
        n = _noticia(self.db)
        self.db.guardar_agenda_item("2026-08-12", "09:30", "normal", "local", n.id, AHORA.isoformat())
        fake_falla_verificacion = FakeClienteMeta(fallar_verificacion_story=True)

        publicar_franja(
            self.db, "2026-08-12", "09:30",
            cliente_fb=fake_falla_verificacion, cliente_ig=fake_falla_verificacion, ahora=AHORA,
        )
        fila_story = self.db.obtener_programacion_meta("2026-08-12", "09:30", "instagram_story")
        self.assertEqual(fila_story["estado"], "error")
        media_id_ya_confirmado = fila_story["meta_id"]
        self.assertIsNotNone(media_id_ya_confirmado)  # Meta ya la publicó, solo falló el GET

        fake_ok = FakeClienteMeta()
        resultado_reintento = publicar_franja(
            self.db, "2026-08-12", "09:30", cliente_fb=fake_ok, cliente_ig=fake_ok, ahora=AHORA
        )

        estados = {r.red_social: r.estado for r in resultado_reintento.redes}
        self.assertEqual(estados["instagram_story"], "publicado")
        # nunca se vuelve a alojar la imagen ni a crear el contenedor: solo se reverifica
        self.assertFalse(any(nombre == "alojar_imagen_para_story" for nombre, _ in fake_ok.llamadas))
        self.assertFalse(any(nombre == "publicar_instagram_story" for nombre, _ in fake_ok.llamadas))
        fila_final = self.db.obtener_programacion_meta("2026-08-12", "09:30", "instagram_story")
        self.assertEqual(fila_final["meta_id"], media_id_ya_confirmado)

    def test_idempotente_no_vuelve_a_publicar_una_story_ya_publicada(self):
        n = _noticia(self.db)
        self.db.guardar_agenda_item("2026-08-12", "09:30", "normal", "local", n.id, AHORA.isoformat())
        fake = FakeClienteMeta()

        publicar_franja(self.db, "2026-08-12", "09:30", cliente_fb=fake, cliente_ig=fake, ahora=AHORA)
        llamadas_antes = len(fake.llamadas)
        resultado = publicar_franja(self.db, "2026-08-12", "09:30", cliente_fb=fake, cliente_ig=fake, ahora=AHORA)

        estados = {r.red_social: r.estado for r in resultado.redes}
        self.assertEqual(estados["instagram_story"], "omitido")
        self.assertEqual(len(fake.llamadas), llamadas_antes)

    def test_deshabilitada_por_configuracion_no_intenta_nada(self):
        n = _noticia(self.db)
        self.db.guardar_agenda_item("2026-08-12", "09:30", "normal", "local", n.id, AHORA.isoformat())
        fake = FakeClienteMeta()

        with patch("motor_noticias.meta.publicador._historias_instagram_habilitadas", return_value=False):
            resultado = publicar_franja(
                self.db, "2026-08-12", "09:30", cliente_fb=fake, cliente_ig=fake, ahora=AHORA
            )

        redes = {r.red_social for r in resultado.redes}
        self.assertNotIn("instagram_story", redes)
        self.assertIsNone(self.db.obtener_programacion_meta("2026-08-12", "09:30", "instagram_story"))
        self.assertFalse(any(n in ("alojar_imagen_para_story", "publicar_instagram_story") for n, _ in fake.llamadas))

    def test_story_tambien_se_publica_por_el_circuito_de_urgentes(self):
        n = _noticia(self.db)
        self.db.guardar_agenda_item("2026-08-12", None, "urgente", "local", n.id, AHORA.isoformat())
        fake = FakeClienteMeta()

        resultados = publicar_urgentes(self.db, "2026-08-12", cliente_fb=fake, cliente_ig=fake, ahora=AHORA)

        self.assertEqual(len(resultados), 1)
        estados = {r.red_social: r.estado for r in resultados[0].redes}
        self.assertEqual(estados["instagram_story"], "publicado")

    def test_story_no_se_publica_si_la_noticia_esta_pendiente_de_revision(self):
        n = _noticia(self.db, requiere_revision_especial=True, categoria_riesgo="judicial")
        self.db.guardar_agenda_item("2026-08-12", "09:30", "normal", "local", n.id, AHORA.isoformat())
        fake = FakeClienteMeta()

        resultado = publicar_franja(self.db, "2026-08-12", "09:30", cliente_fb=fake, cliente_ig=fake, ahora=AHORA)

        self.assertEqual(resultado.resultado, "pendiente_revision_humana")
        self.assertIsNone(self.db.obtener_programacion_meta("2026-08-12", "09:30", "instagram_story"))
        self.assertEqual(fake.llamadas, [])


class TestPublicarInstitucional(BaseTest):
    """Publicación institucional diaria (motor_noticias.institucional):
    misma imagen y texto todos los días, en su propia franja fija (19:30),
    sin Story y sin que la deduplicación general la bloquee día a día."""

    def test_publica_facebook_e_instagram_feed(self):
        entrada = reservar_franja_institucional(self.db, ahora=AHORA)
        fake = FakeClienteMeta()

        resultado = publicar_franja(
            self.db, entrada.fecha, HORA_INSTITUCIONAL, cliente_fb=fake, cliente_ig=fake, ahora=AHORA
        )

        self.assertEqual(resultado.resultado, "procesada")
        estados = {r.red_social: r.estado for r in resultado.redes}
        self.assertEqual(estados, {"facebook": "publicado", "instagram": "publicado"})
        self.assertEqual(self.db.obtener(entrada.noticia_id)["estado"], Estado.PUBLICADA.value)

    def test_nunca_genera_instagram_story(self):
        entrada = reservar_franja_institucional(self.db, ahora=AHORA)
        fake = FakeClienteMeta()

        resultado = publicar_franja(
            self.db, entrada.fecha, HORA_INSTITUCIONAL, cliente_fb=fake, cliente_ig=fake, ahora=AHORA
        )

        redes = {r.red_social for r in resultado.redes}
        self.assertNotIn("instagram_story", redes)
        self.assertIsNone(
            self.db.obtener_programacion_meta(entrada.fecha, HORA_INSTITUCIONAL, "instagram_story")
        )
        self.assertFalse(any(n in ("alojar_imagen_para_story", "publicar_instagram_story") for n, _ in fake.llamadas))

    def test_usa_la_imagen_configurada_no_genera_una_placa_nueva(self):
        entrada = reservar_franja_institucional(self.db, ahora=AHORA)
        noticia = self.db.obtener(entrada.noticia_id)
        ruta_imagen_esperada = noticia["imagen_publicacion_ruta"]
        fake = FakeClienteMeta()

        publicar_franja(self.db, entrada.fecha, HORA_INSTITUCIONAL, cliente_fb=fake, cliente_ig=fake, ahora=AHORA)

        llamada_fb = next(v for n, v in fake.llamadas if n == "publicar_foto_facebook")
        self.assertEqual(llamada_fb, ruta_imagen_esperada)
        # nunca se marca como "generada automáticamente": es la imagen fija configurada.
        self.assertFalse(self.db.obtener(entrada.noticia_id)["imagen_generada_automaticamente"])

    def test_no_se_publica_dos_veces_el_mismo_dia_ni_con_reintento(self):
        entrada = reservar_franja_institucional(self.db, ahora=AHORA)
        fake = FakeClienteMeta()

        publicar_franja(self.db, entrada.fecha, HORA_INSTITUCIONAL, cliente_fb=fake, cliente_ig=fake, ahora=AHORA)
        llamadas_antes = len(fake.llamadas)

        # Reservar de nuevo el mismo día (idempotente) y volver a publicar
        # (como pasaría en el próximo ciclo del Motor, o un reintento).
        reservar_franja_institucional(self.db, ahora=AHORA)
        resultado_2 = publicar_franja(
            self.db, entrada.fecha, HORA_INSTITUCIONAL, cliente_fb=fake, cliente_ig=fake, ahora=AHORA
        )

        estados = {r.red_social: r.estado for r in resultado_2.redes}
        self.assertEqual(estados, {"facebook": "omitido", "instagram": "omitido"})
        self.assertEqual(len(fake.llamadas), llamadas_antes)  # ningún POST nuevo

        # Vía reintentar_publicaciones también, por si quedó en error.
        resultados_reintento = reintentar_publicaciones(self.db, cliente_fb=fake, cliente_ig=fake, ahora=AHORA)
        self.assertEqual(resultados_reintento, [])  # nada en estado 'error': no hay nada que reintentar
        self.assertEqual(len(fake.llamadas), llamadas_antes)

    def test_no_bloqueada_por_deduplicacion_general_al_dia_siguiente(self):
        # El texto y la imagen son intencionalmente idénticos día a día: la
        # deduplicación general (por fingerprint de contenido) NO debe
        # bloquear la institucional de hoy contra la de ayer.
        ahora_dia_1 = AHORA
        ahora_dia_2 = AHORA.replace(day=13)
        fake = FakeClienteMeta()

        entrada_1 = reservar_franja_institucional(self.db, ahora=ahora_dia_1)
        publicar_franja(
            self.db, entrada_1.fecha, HORA_INSTITUCIONAL, cliente_fb=fake, cliente_ig=fake, ahora=ahora_dia_1
        )

        entrada_2 = reservar_franja_institucional(self.db, ahora=ahora_dia_2)
        self.assertNotEqual(entrada_1.noticia_id, entrada_2.noticia_id)

        resultado_2 = publicar_franja(
            self.db, entrada_2.fecha, HORA_INSTITUCIONAL, cliente_fb=fake, cliente_ig=fake, ahora=ahora_dia_2
        )

        self.assertEqual(resultado_2.resultado, "procesada")
        estados = {r.red_social: r.estado for r in resultado_2.redes}
        self.assertEqual(estados, {"facebook": "publicado", "instagram": "publicado"})

    def test_no_interfiere_con_la_deduplicacion_de_noticias_reales(self):
        # Control: una noticia real que sí comparte contenido con otra
        # noticia real sigue bloqueándose como siempre (la excepción es
        # solo para origen_ingreso="institucional", no para todo el sistema).
        a = _noticia(
            self.db, 1,
            titulo_original="Independiente Rivadavia apuesta por sorprender como local a un Fluminense sin entrenador",
            titulo_preparado="Independiente Rivadavia apuesta por sorprender como local a un Fluminense sin entrenador",
        )
        b = _noticia(
            self.db, 2,
            titulo_original="Independiente Rivadavia busca hacer historia ante Fluminense en la Copa Libertadores",
            titulo_preparado="Independiente Rivadavia busca hacer historia ante Fluminense en la Copa Libertadores",
        )
        self.db.guardar_agenda_item("2026-08-12", "09:30", "normal", "local", a.id, AHORA.isoformat())
        self.db.guardar_agenda_item("2026-08-12", "10:00", "normal", "local", b.id, AHORA.isoformat())
        fake = FakeClienteMeta()

        publicar_franja(self.db, "2026-08-12", "09:30", cliente_fb=fake, cliente_ig=fake, ahora=AHORA)
        resultado_b = publicar_franja(self.db, "2026-08-12", "10:00", cliente_fb=fake, cliente_ig=fake, ahora=AHORA)

        self.assertEqual(resultado_b.resultado, "duplicado_bloqueado")


if __name__ == "__main__":
    unittest.main()
