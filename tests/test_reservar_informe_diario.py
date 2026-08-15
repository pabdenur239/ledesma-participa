import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from motor_noticias.db import Database
from motor_noticias.dedupe import hash_contenido, normalizar_url
from motor_noticias.models import Estado, Noticia, RevisionEstado
from motor_noticias.motor_editorial import HORA_INFORME_DIARIO, reservar_franja_informe_diario

AHORA = datetime(2026, 8, 12, 12, 0, 0, tzinfo=timezone.utc)  # 09:00 Jujuy


def _informe(db: Database, fecha_iso: str, estado=Estado.PREPARADA.value, revision=RevisionEstado.PENDIENTE.value):
    url = f"https://ledesma-participa.local/informe-diario/{fecha_iso}"
    n = Noticia(
        id=None,
        titulo_original="Clima y dólar",
        texto_original="texto",
        url_fuente=url,
        url_normalizada=normalizar_url(url),
        nombre_fuente="Informe Diario",
        fecha_fuente="",
        fecha_recoleccion=AHORA.isoformat(),
        estado=estado,
        hash_contenido=hash_contenido("Clima y dólar", "texto"),
        territorio="local",
        revision_estado=revision,
        titulo_preparado="Clima y dólar",
        texto_preparado="texto",
    )
    db.guardar(n)
    return n


class TestReservarInformeDiario(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmpdir.name) / "test.db")

    def tearDown(self):
        self.db.close()
        self.tmpdir.cleanup()

    def test_reserva_el_informe_del_dia_en_0730(self):
        informe = _informe(self.db, "2026-08-12")

        entrada = reservar_franja_informe_diario(self.db, fecha="2026-08-12", ahora=AHORA)

        self.assertEqual(entrada.hora, HORA_INFORME_DIARIO)
        self.assertEqual(entrada.noticia_id, informe.id)
        self.assertEqual(entrada.estado, "creado")

    def test_sin_informe_generado_queda_sin_candidato(self):
        entrada = reservar_franja_informe_diario(self.db, fecha="2026-08-12", ahora=AHORA)

        self.assertEqual(entrada.estado, "sin_candidato")
        self.assertIsNone(entrada.noticia_id)

    def test_informe_excluido_de_la_cascada_normal_al_quedar_usado(self):
        informe = _informe(self.db, "2026-08-12")
        reservar_franja_informe_diario(self.db, fecha="2026-08-12", ahora=AHORA)

        self.assertIn(informe.id, self.db.noticias_ids_usadas_en_agenda())

    def test_informe_rechazado_nunca_se_reserva(self):
        _informe(self.db, "2026-08-12", revision=RevisionEstado.RECHAZADA.value)

        entrada = reservar_franja_informe_diario(self.db, fecha="2026-08-12", ahora=AHORA)

        self.assertEqual(entrada.estado, "sin_candidato")

    def test_franja_aprobada_no_se_reemplaza_por_otro_informe(self):
        primero = _informe(self.db, "2026-08-12")
        reservar_franja_informe_diario(self.db, fecha="2026-08-12", ahora=AHORA)
        self.db.actualizar_revision(primero.id, RevisionEstado.APROBADA.value, "t", "x", AHORA.isoformat())

        entrada = reservar_franja_informe_diario(self.db, fecha="2026-08-12", ahora=AHORA)

        self.assertEqual(entrada.estado, "existente")
        self.assertEqual(entrada.noticia_id, primero.id)

    def test_franja_pasada_no_se_reevalua_retrospectivamente(self):
        ahora_tarde = AHORA + timedelta(hours=4)  # 13:00 Jujuy, 07:30 ya pasó
        reservar_franja_informe_diario(self.db, fecha="2026-08-12", ahora=ahora_tarde)
        _informe(self.db, "2026-08-12")  # llega después de evaluada la franja

        entrada = reservar_franja_informe_diario(self.db, fecha="2026-08-12", ahora=ahora_tarde + timedelta(minutes=5))

        self.assertEqual(entrada.estado, "sin_candidato")


if __name__ == "__main__":
    unittest.main()
