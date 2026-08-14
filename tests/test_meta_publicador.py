import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from motor_noticias.db import Database
from motor_noticias.dedupe import hash_contenido, normalizar_url
from motor_noticias.meta.cliente import ErrorClienteMeta
from motor_noticias.meta.publicador import publicar_franja, reintentar_publicaciones
from motor_noticias.models import Estado, Noticia

AHORA = datetime(2026, 8, 12, 12, 0, 0, tzinfo=timezone.utc)


class FakeClienteMeta:
    """Simulador de Meta para pruebas offline: nunca hace una petición de
    red real. Configurable para éxito o fallo por llamada, y registra qué se
    invocó para poder verificar el comportamiento."""

    def __init__(self, fallar_facebook=False, fallar_instagram=False):
        self.fallar_facebook = fallar_facebook
        self.fallar_instagram = fallar_instagram
        self.llamadas = []

    def publicar_foto_facebook(self, contenido, ruta_imagen, dry_run=True):
        self.llamadas.append(("publicar_foto_facebook", str(ruta_imagen)))
        if self.fallar_facebook:
            raise ErrorClienteMeta("fallo simulado de Facebook")
        return "post-fb-123"

    def publicar_foto_facebook_por_url(self, contenido, imagen_url, dry_run=True):
        self.llamadas.append(("publicar_foto_facebook_por_url", imagen_url))
        if self.fallar_facebook:
            raise ErrorClienteMeta("fallo simulado de Facebook")
        return "post-fb-123"

    def publicar_comentario_facebook(self, post_id, texto, dry_run=True):
        self.llamadas.append(("publicar_comentario_facebook", post_id))
        return "comentario-fb-1"

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

    def test_publica_en_ambas_redes_y_confirma_ids_reales(self):
        n = _noticia(self.db)
        self.db.guardar_agenda_item("2026-08-12", "09:30", "normal", "local", n.id, AHORA.isoformat())
        fake = FakeClienteMeta()

        resultado = publicar_franja(
            self.db, "2026-08-12", "09:30",
            cliente_fb=fake, cliente_ig=fake, image_base_url="https://ejemplo.local/placas", ahora=AHORA,
        )

        self.assertEqual(resultado.resultado, "procesada")
        estados = {r.red_social: r.estado for r in resultado.redes}
        self.assertEqual(estados, {"facebook": "publicado", "instagram": "publicado"})

        fila_fb = self.db.obtener_programacion_meta("2026-08-12", "09:30", "facebook")
        fila_ig = self.db.obtener_programacion_meta("2026-08-12", "09:30", "instagram")
        self.assertEqual(fila_fb["meta_id"], "post-fb-123")
        self.assertEqual(fila_ig["meta_id"], "media-ig-456")
        self.assertEqual(self.db.obtener(n.id)["estado"], Estado.PUBLICADA.value)

    def test_fallo_de_instagram_no_afecta_el_estado_de_facebook(self):
        n = _noticia(self.db)
        self.db.guardar_agenda_item("2026-08-12", "09:30", "normal", "local", n.id, AHORA.isoformat())
        fake = FakeClienteMeta(fallar_instagram=True)

        resultado = publicar_franja(
            self.db, "2026-08-12", "09:30",
            cliente_fb=fake, cliente_ig=fake, image_base_url="https://ejemplo.local/placas", ahora=AHORA,
        )

        estados = {r.red_social: r.estado for r in resultado.redes}
        self.assertEqual(estados["facebook"], "publicado")
        self.assertEqual(estados["instagram"], "error")

        fila_fb = self.db.obtener_programacion_meta("2026-08-12", "09:30", "facebook")
        fila_ig = self.db.obtener_programacion_meta("2026-08-12", "09:30", "instagram")
        self.assertEqual(fila_fb["estado"], "publicado")
        self.assertEqual(fila_ig["estado"], "error")

    def test_idempotencia_no_vuelve_a_publicar_una_franja_ya_publicada(self):
        n = _noticia(self.db)
        self.db.guardar_agenda_item("2026-08-12", "09:30", "normal", "local", n.id, AHORA.isoformat())
        fake = FakeClienteMeta()

        publicar_franja(self.db, "2026-08-12", "09:30", cliente_fb=fake, cliente_ig=fake,
                         image_base_url="https://ejemplo.local/placas", ahora=AHORA)
        llamadas_primera_vez = len(fake.llamadas)
        resultado = publicar_franja(self.db, "2026-08-12", "09:30", cliente_fb=fake, cliente_ig=fake,
                                     image_base_url="https://ejemplo.local/placas", ahora=AHORA)

        estados = {r.red_social: r.estado for r in resultado.redes}
        self.assertEqual(estados, {"facebook": "omitido", "instagram": "omitido"})
        self.assertEqual(len(fake.llamadas), llamadas_primera_vez)  # ninguna llamada nueva

    def test_sin_image_base_url_instagram_queda_en_error_pero_facebook_publica(self):
        n = _noticia(self.db)
        self.db.guardar_agenda_item("2026-08-12", "09:30", "normal", "local", n.id, AHORA.isoformat())
        fake = FakeClienteMeta()

        resultado = publicar_franja(self.db, "2026-08-12", "09:30", cliente_fb=fake, cliente_ig=fake,
                                     image_base_url=None, ahora=AHORA)

        estados = {r.red_social: r.estado for r in resultado.redes}
        self.assertEqual(estados["facebook"], "publicado")
        self.assertEqual(estados["instagram"], "error")


class TestReintentarPublicaciones(BaseTest):
    def test_reintenta_solo_la_red_que_fallo(self):
        n = _noticia(self.db)
        self.db.guardar_agenda_item("2026-08-12", "09:30", "normal", "local", n.id, AHORA.isoformat())
        fake_falla = FakeClienteMeta(fallar_instagram=True)
        publicar_franja(self.db, "2026-08-12", "09:30", cliente_fb=fake_falla, cliente_ig=fake_falla,
                         image_base_url="https://ejemplo.local/placas", ahora=AHORA)

        fake_ok = FakeClienteMeta()
        resultados = reintentar_publicaciones(
            self.db, cliente_fb=fake_ok, cliente_ig=fake_ok,
            image_base_url="https://ejemplo.local/placas", ahora=AHORA,
        )

        self.assertEqual(len(resultados), 1)
        estados = {r.red_social: r.estado for r in resultados[0].redes}
        self.assertEqual(estados["facebook"], "omitido")  # ya estaba publicado, no se repite
        self.assertEqual(estados["instagram"], "publicado")

    def test_no_reintenta_mas_alla_del_maximo_de_intentos(self):
        n = _noticia(self.db)
        self.db.guardar_agenda_item("2026-08-12", "09:30", "normal", "local", n.id, AHORA.isoformat())
        fake_falla = FakeClienteMeta(fallar_facebook=True, fallar_instagram=True)

        for _ in range(3):
            publicar_franja(self.db, "2026-08-12", "09:30", cliente_fb=fake_falla, cliente_ig=fake_falla,
                             image_base_url="https://ejemplo.local/placas", ahora=AHORA)

        pendientes = self.db.listar_programacion_meta_para_reintentar(max_intentos=3)
        self.assertEqual(pendientes, [])  # ya alcanzaron el máximo, no se reintentan más


if __name__ == "__main__":
    unittest.main()
