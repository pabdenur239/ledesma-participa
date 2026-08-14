import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from motor_noticias.db import Database
from motor_noticias.dedupe import hash_contenido, normalizar_url
from motor_noticias.meta.programacion import aprobar_si_elegible, generar_placas_del_dia
from motor_noticias.models import Estado, Noticia, RevisionEstado

AHORA = datetime(2026, 8, 12, 12, 0, 0, tzinfo=timezone.utc)


def _noticia(db, **overrides):
    base = dict(
        id=None,
        titulo_original="Título",
        texto_original="Texto de la noticia con contenido suficiente para reseña.",
        url_fuente=f"http://a.com/{overrides.get('_n', 1)}",
        nombre_fuente="Prensa Jujuy",
        fecha_fuente="",
        fecha_recoleccion=AHORA.isoformat(),
        estado=Estado.PREPARADA.value,
        hash_contenido="",
        territorio="local",
        titulo_preparado="Título",
        texto_preparado="Texto de la noticia con contenido suficiente para reseña.",
    )
    overrides.pop("_n", None)
    base.update(overrides)
    url = base["url_fuente"]
    base["url_normalizada"] = normalizar_url(url)
    base["hash_contenido"] = hash_contenido(base["titulo_original"], base["texto_original"] + url)
    n = Noticia(**base)
    db.guardar(n)
    return n


class BaseTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmpdir.name) / "test.db")

    def tearDown(self):
        self.db.close()
        self.tmpdir.cleanup()


class TestAprobarSiElegible(BaseTest):
    def test_noticia_apta_se_aprueba_automaticamente(self):
        n = _noticia(self.db)
        actualizada = aprobar_si_elegible(self.db, self.db.obtener(n.id), ahora=AHORA)
        self.assertEqual(actualizada["revision_estado"], RevisionEstado.APROBADA.value)
        self.assertEqual(actualizada["revision_automatica"], 1)

    def test_noticia_con_riesgo_editorial_no_se_aprueba(self):
        n = _noticia(self.db, requiere_revision_especial=True, categoria_riesgo="judicial")
        actualizada = aprobar_si_elegible(self.db, self.db.obtener(n.id), ahora=AHORA)
        self.assertEqual(actualizada["revision_estado"], RevisionEstado.PENDIENTE.value)

    def test_ya_aprobada_manualmente_no_se_toca(self):
        n = _noticia(self.db)
        self.db.actualizar_revision(n.id, RevisionEstado.APROBADA.value, "T", "X", AHORA.isoformat(), automatica=False)
        actualizada = aprobar_si_elegible(self.db, self.db.obtener(n.id), ahora=AHORA)
        self.assertEqual(actualizada["revision_automatica"], 0)  # sigue como aprobación humana


class TestGenerarPlacasDelDia(BaseTest):
    def test_franja_con_contenido_apto_queda_lista(self):
        n = _noticia(self.db, _n=1)
        self.db.guardar_agenda_item("2026-08-12", "09:30", "normal", "local", n.id, AHORA.isoformat())

        resultados = generar_placas_del_dia(self.db, fecha="2026-08-12", ahora=AHORA)

        self.assertEqual(len(resultados), 1)
        self.assertEqual(resultados[0].resultado, "placa_lista")

    def test_franja_sin_contenido_se_ignora(self):
        self.db.guardar_agenda_item("2026-08-12", "09:30", "normal", None, None, AHORA.isoformat())

        resultados = generar_placas_del_dia(self.db, fecha="2026-08-12", ahora=AHORA)

        self.assertEqual(resultados, [])

    def test_noticia_con_riesgo_editorial_queda_pendiente_de_revision_humana(self):
        n = _noticia(self.db, _n=2, requiere_revision_especial=True, categoria_riesgo="politica_partidaria")
        self.db.guardar_agenda_item("2026-08-12", "11:30", "normal", "local", n.id, AHORA.isoformat())

        resultados = generar_placas_del_dia(self.db, fecha="2026-08-12", ahora=AHORA)

        self.assertEqual(resultados[0].resultado, "pendiente_revision_humana")

    def test_varias_franjas_del_dia_se_procesan_todas(self):
        n1 = _noticia(self.db, _n=3)
        n2 = _noticia(self.db, _n=4)
        self.db.guardar_agenda_item("2026-08-12", "09:30", "normal", "local", n1.id, AHORA.isoformat())
        self.db.guardar_agenda_item("2026-08-12", "11:30", "normal", "local", n2.id, AHORA.isoformat())

        resultados = generar_placas_del_dia(self.db, fecha="2026-08-12", ahora=AHORA)

        self.assertEqual(len(resultados), 2)
        self.assertTrue(all(r.resultado == "placa_lista" for r in resultados))


if __name__ == "__main__":
    unittest.main()
