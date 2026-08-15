import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from motor_noticias.db import Database
from motor_noticias.dedupe import hash_contenido, normalizar_url
from motor_noticias.meta.cliente import ErrorClienteMeta, ResultadoFotoFacebook
from motor_noticias.meta.publicador import publicar_franja, reintentar_publicaciones
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
    ):
        self.fallar_facebook = fallar_facebook
        self.fallar_instagram = fallar_instagram
        self.fallar_obtener_url = fallar_obtener_url
        self.fallar_verificacion = fallar_verificacion
        self.llamadas = []
        self._contador_fotos = 0

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
        self.assertEqual(estados, {"facebook": "publicado", "instagram": "publicado"})

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
        self.assertFalse(any(n == "obtener_url_publica_foto" for n, _ in fake.llamadas))

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
        self.assertEqual(estados, {"facebook": "omitido", "instagram": "omitido"})
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


if __name__ == "__main__":
    unittest.main()
