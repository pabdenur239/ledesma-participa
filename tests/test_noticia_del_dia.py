import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from motor_noticias.db import Database
from motor_noticias.models import Estado, Noticia
from motor_noticias.motor_editorial import HORA_NOTICIA_DEL_DIA, ZONA_JUJUY, resolver_urgentes
from motor_noticias.noticia_del_dia import reservar_franja_noticia_del_dia

AHORA = datetime(2026, 8, 21, 13, 0, tzinfo=ZONA_JUJUY)


def _noticia(db, territorio, titulo, urgente=False, categoria_tematica=None, id_sufijo="1"):
    n = Noticia(
        id=None,
        titulo_original=titulo,
        texto_original="Texto de prueba con contenido suficiente.",
        url_fuente=f"https://ejemplo.test/{id_sufijo}",
        url_normalizada=f"https://ejemplo.test/{id_sufijo}",
        nombre_fuente="Fuente de prueba",
        fecha_fuente="",
        fecha_recoleccion=(AHORA.astimezone(timezone.utc) - timedelta(minutes=5)).isoformat(),
        estado=Estado.PREPARADA.value,
        hash_contenido=f"hash-{id_sufijo}",
        territorio=territorio,
        motivo_territorio="prueba",
        titulo_preparado=titulo,
        texto_preparado="Texto preparado.",
        urgente=urgente,
        categoria_tematica=categoria_tematica,
    )
    db.guardar(n)
    return n


class BaseTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmpdir.name) / "test.db")

    def tearDown(self):
        self.db.close()
        self.tmpdir.cleanup()


class TestNoticiaDelDia(BaseTest):
    def test_elige_local_por_sobre_internacional(self):
        _noticia(self.db, "sin_clasificar", "Nota internacional", categoria_tematica="internacional", id_sufijo="a")
        local = _noticia(self.db, "local", "Nota local importante", id_sufijo="b")

        entrada = reservar_franja_noticia_del_dia(self.db, ahora=AHORA)

        self.assertEqual(entrada.noticia_id, local.id)
        self.assertEqual(entrada.hora, HORA_NOTICIA_DEL_DIA)

    def test_cae_a_internacional_si_no_hay_nada_territorial(self):
        internacional = _noticia(
            self.db, "sin_clasificar", "Nota internacional", categoria_tematica="internacional"
        )

        entrada = reservar_franja_noticia_del_dia(self.db, ahora=AHORA)

        self.assertEqual(entrada.noticia_id, internacional.id)

    def test_nunca_cae_a_entretenimiento_generico(self):
        # Solo hay contenido de espectáculos (no internacional): Noticia del
        # Día no debe rellenar con eso, debe quedar sin_candidato.
        _noticia(self.db, "sin_clasificar", "Nota de espectáculos", categoria_tematica="espectaculos")

        entrada = reservar_franja_noticia_del_dia(self.db, ahora=AHORA)

        self.assertEqual(entrada.estado, "sin_candidato")
        self.assertIsNone(entrada.noticia_id)

    def test_no_le_roba_la_noticia_a_una_urgente_recien_marcada(self):
        # Bug real corregido: si se llama resolver_urgentes ANTES (como hace
        # ciclo_continuo._actualizar_agenda), Noticia del Día no debe volver
        # a tomar esa misma noticia.
        local_urgente = _noticia(self.db, "local", "Alerta local urgente", urgente=True)

        usados = self.db.noticias_ids_usadas_en_agenda()
        fecha_limite = (AHORA.astimezone(timezone.utc) - timedelta(hours=48)).isoformat()
        entradas_urgentes = resolver_urgentes(self.db, "2026-08-21", usados, fecha_limite)
        self.assertEqual(len(entradas_urgentes), 1)
        self.assertEqual(entradas_urgentes[0].noticia_id, local_urgente.id)

        entrada_del_dia = reservar_franja_noticia_del_dia(self.db, ahora=AHORA)
        self.assertEqual(entrada_del_dia.estado, "sin_candidato")

        urgentes_en_agenda = [i for i in self.db.listar_agenda("2026-08-21") if i["tipo"] == "urgente"]
        self.assertEqual(len(urgentes_en_agenda), 1)

    def test_llamar_dos_veces_no_duplica(self):
        local = _noticia(self.db, "local", "Nota local")

        entrada_1 = reservar_franja_noticia_del_dia(self.db, ahora=AHORA)
        entrada_2 = reservar_franja_noticia_del_dia(self.db, ahora=AHORA)

        self.assertEqual(entrada_1.noticia_id, local.id)
        self.assertEqual(entrada_2.noticia_id, local.id)
        self.assertEqual(entrada_2.estado, "existente")
        self.assertEqual(len(self.db.listar_agenda("2026-08-21")), 1)


if __name__ == "__main__":
    unittest.main()
