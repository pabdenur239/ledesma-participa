import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from motor_noticias.db import Database
from motor_noticias.institucional import (
    HORA_INSTITUCIONAL,
    TERRITORIO_INSTITUCIONAL,
    reservar_franja_institucional,
)
from motor_noticias.models import OrigenIngreso, RevisionEstado
from motor_noticias.motor_editorial import ORDEN_CASCADA, ZONA_JUJUY, generar_agenda

AHORA = datetime(2026, 8, 21, 20, 30, tzinfo=ZONA_JUJUY)
AHORA_SIGUIENTE_DIA = datetime(2026, 8, 22, 20, 30, tzinfo=ZONA_JUJUY)


class BaseInstitucionalTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmpdir.name) / "test.db")
        self.parche_placas = None

    def tearDown(self):
        self.db.close()
        self.tmpdir.cleanup()


class TestReservarFranjaInstitucional(BaseInstitucionalTest):
    def test_crea_la_institucional_del_dia(self):
        entrada = reservar_franja_institucional(self.db, ahora=AHORA)

        self.assertEqual(entrada.fecha, "2026-08-21")
        self.assertEqual(entrada.hora, HORA_INSTITUCIONAL)
        self.assertEqual(entrada.tipo, "normal")
        self.assertEqual(entrada.estado, "creado")
        self.assertIsNotNone(entrada.noticia_id)

        noticia = self.db.obtener(entrada.noticia_id)
        self.assertEqual(noticia["territorio"], TERRITORIO_INSTITUCIONAL)
        self.assertEqual(noticia["origen_ingreso"], OrigenIngreso.INSTITUCIONAL.value)
        self.assertEqual(noticia["revision_estado"], RevisionEstado.APROBADA.value)
        self.assertTrue(noticia["revision_automatica"])
        self.assertFalse(noticia["requiere_revision_especial"])
        self.assertTrue(noticia["tiene_imagen_original"])
        self.assertIsNotNone(noticia["imagen_publicacion_ruta"])
        self.assertTrue(Path(noticia["imagen_publicacion_ruta"]).exists())

    def test_texto_no_incluye_url_interna_de_identidad(self):
        entrada = reservar_franja_institucional(self.db, ahora=AHORA)
        noticia = self.db.obtener(entrada.noticia_id)
        # url_fuente queda vacía a propósito (ver institucional.py): la URL
        # interna `ledesma-participa.local/institucional/...` es solo un
        # identificador, nunca debe aparecer en el post real.
        self.assertEqual(noticia["url_fuente"], "")
        self.assertNotIn("ledesma-participa.local", noticia["texto_preparado"])
        self.assertIn("ledesmaparticipa.com.ar", noticia["texto_preparado"])

    def test_llamar_dos_veces_el_mismo_dia_no_duplica(self):
        entrada_1 = reservar_franja_institucional(self.db, ahora=AHORA)
        entrada_2 = reservar_franja_institucional(self.db, ahora=AHORA)

        self.assertEqual(entrada_1.noticia_id, entrada_2.noticia_id)
        self.assertEqual(entrada_2.estado, "existente")
        institucionales = [n for n in self.db.listar() if n["origen_ingreso"] == OrigenIngreso.INSTITUCIONAL.value]
        self.assertEqual(len(institucionales), 1)
        self.assertEqual(len(self.db.listar_agenda("2026-08-21")), 1)

    def test_dias_distintos_generan_registros_distintos_y_pueden_variar_texto_e_imagen(self):
        entrada_1 = reservar_franja_institucional(self.db, ahora=AHORA)
        entrada_2 = reservar_franja_institucional(self.db, ahora=AHORA_SIGUIENTE_DIA)

        self.assertNotEqual(entrada_1.noticia_id, entrada_2.noticia_id)
        self.assertEqual(entrada_2.fecha, "2026-08-22")
        self.assertEqual(entrada_2.estado, "creado")

        institucionales = [n for n in self.db.listar() if n["origen_ingreso"] == OrigenIngreso.INSTITUCIONAL.value]
        self.assertEqual(len(institucionales), 2)

    def test_misma_fecha_siempre_elige_la_misma_variante(self):
        # Estabilidad dentro del mismo día (varias corridas del ciclo no
        # deben generar textos distintos para el mismo día): la variante se
        # elige de forma determinística por fecha, no al azar.
        entrada_1 = reservar_franja_institucional(self.db, ahora=AHORA)
        n1 = self.db.obtener(entrada_1.noticia_id)

        db2 = Database(Path(self.tmpdir.name) / "test2.db")
        entrada_2 = reservar_franja_institucional(db2, ahora=AHORA)
        n2 = db2.obtener(entrada_2.noticia_id)
        db2.close()

        self.assertEqual(n1["titulo_preparado"], n2["titulo_preparado"])
        self.assertEqual(n1["texto_preparado"], n2["texto_preparado"])

    def test_rota_entre_variantes_configuradas_segun_el_dia(self):
        from motor_noticias.institucional import _elegir_variante, _cargar_config

        config = _cargar_config()
        variantes_config = config["variantes"]
        self.assertGreaterEqual(len(variantes_config), 2, "debe haber más de una variante para poder rotar")

        elegidas = {_elegir_variante(f"2026-08-{dia:02d}", config)["titulo"] for dia in range(1, 20)}
        self.assertGreater(len(elegidas), 1, "distintos días deben poder elegir distintas variantes")

    def test_franja_reservada_exactamente_a_las_20_30(self):
        entrada = reservar_franja_institucional(self.db, ahora=AHORA)
        item = self.db.obtener_agenda_item("2026-08-21", "20:30")
        self.assertIsNotNone(item)
        self.assertEqual(item["noticia_id"], entrada.noticia_id)
        self.assertEqual(HORA_INSTITUCIONAL, "20:30")


class TestInstitucionalNoInterfiereConLaCascadaNormal(BaseInstitucionalTest):
    def test_no_es_candidata_de_ninguna_franja_normal(self):
        # La cascada normal ("Oportunidades") nunca debe poder seleccionar
        # la institucional para otra franja: territorio="institucional" no
        # está en ORDEN_CASCADA, así que candidato_editorial no la ve ni
        # como último recurso.
        self.assertNotIn(TERRITORIO_INSTITUCIONAL, ORDEN_CASCADA)
        reservar_franja_institucional(self.db, ahora=AHORA)

        entradas = generar_agenda(self.db, fecha="2026-08-21", horarios=("10:30",), ahora=AHORA)

        self.assertEqual(entradas[0].estado, "sin_candidato")
        self.assertIsNone(entradas[0].noticia_id)

    def test_generar_agenda_no_toca_la_franja_institucional(self):
        entrada_institucional = reservar_franja_institucional(self.db, ahora=AHORA)

        # generar_agenda no conoce horarios=("19:30",) salvo que se le pida
        # explícitamente (no forma parte de HORARIOS_DEFAULT); igual se
        # verifica que si se le pidiera, no reemplaza lo ya reservado.
        generar_agenda(self.db, fecha="2026-08-21", horarios=(HORA_INSTITUCIONAL,), ahora=AHORA)

        item = self.db.obtener_agenda_item("2026-08-21", HORA_INSTITUCIONAL)
        self.assertEqual(item["noticia_id"], entrada_institucional.noticia_id)


if __name__ == "__main__":
    unittest.main()
