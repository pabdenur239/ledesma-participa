import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from motor_noticias.alertas import calcular_alertas
from motor_noticias.db import Database
from motor_noticias.models import Estado, Noticia

AHORA = datetime(2026, 8, 12, 18, 0, 0, tzinfo=timezone.utc)


def _iso(delta: timedelta) -> str:
    return (AHORA - delta).isoformat()


def _noticia_relevante(fecha_recoleccion: str) -> Noticia:
    return Noticia(
        id=None,
        titulo_original="Obras en Libertador General San Martín",
        texto_original="Contenido de prueba.",
        url_fuente="https://ejemplo.test/1",
        url_normalizada="https://ejemplo.test/1",
        nombre_fuente="Fuente de prueba",
        fecha_fuente="",
        fecha_recoleccion=fecha_recoleccion,
        estado=Estado.PREPARADA.value,
        hash_contenido="hash-1",
        relevancia_local=True,
    )


class TestAlertaFuenteConFallas(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmpdir.name) / "test.db")

    def tearDown(self):
        self.db.close()
        self.tmpdir.cleanup()

    def test_no_hay_alerta_con_menos_de_tres_fallos(self):
        self.db.registrar_salud_fuente("fuente-a", "error", mensaje_error="fallo", fecha_consulta=_iso(timedelta()))
        self.db.registrar_salud_fuente("fuente-a", "error", mensaje_error="fallo", fecha_consulta=_iso(timedelta()))

        alertas = calcular_alertas(self.db, ahora=AHORA)

        self.assertFalse(any(a["tipo"] == "fuente_con_fallas" for a in alertas))

    def test_alerta_tras_tres_fallos_consecutivos(self):
        for _ in range(3):
            self.db.registrar_salud_fuente(
                "fuente-a", "error", mensaje_error="fallo", fecha_consulta=_iso(timedelta())
            )

        alertas = calcular_alertas(self.db, ahora=AHORA)

        alertas_fuente = [a for a in alertas if a["tipo"] == "fuente_con_fallas"]
        self.assertEqual(len(alertas_fuente), 1)
        self.assertEqual(alertas_fuente[0]["nivel"], "ERROR")
        self.assertEqual(alertas_fuente[0]["fuente"], "fuente-a")


class TestAlertaFuenteInactiva(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmpdir.name) / "test.db")

    def tearDown(self):
        self.db.close()
        self.tmpdir.cleanup()

    def test_no_hay_alerta_si_entrego_noticias_hace_menos_de_24_horas(self):
        self.db.registrar_salud_fuente(
            "fuente-a", "ok", elementos_obtenidos=2, noticias_nuevas=1, fecha_consulta=_iso(timedelta(hours=2))
        )

        alertas = calcular_alertas(self.db, ahora=AHORA)

        self.assertFalse(any(a["tipo"] == "fuente_inactiva" for a in alertas))

    def test_alerta_tras_24_horas_sin_entregar_noticias(self):
        # respondió OK con contenido hace 30 horas y no volvió a traer nada nuevo desde entonces.
        self.db.registrar_salud_fuente(
            "fuente-a", "ok", elementos_obtenidos=3, noticias_nuevas=1, fecha_consulta=_iso(timedelta(hours=30))
        )
        self.db.registrar_salud_fuente(
            "fuente-a", "ok", elementos_obtenidos=3, noticias_nuevas=0, fecha_consulta=_iso(timedelta())
        )

        alertas = calcular_alertas(self.db, ahora=AHORA)

        alertas_inactiva = [a for a in alertas if a["tipo"] == "fuente_inactiva"]
        self.assertEqual(len(alertas_inactiva), 1)
        self.assertEqual(alertas_inactiva[0]["nivel"], "ADVERTENCIA")
        self.assertEqual(alertas_inactiva[0]["fuente"], "fuente-a")

    def test_fuente_con_error_no_dispara_alerta_de_inactividad_por_separado(self):
        # una fuente caída ya se refleja en "fuente_con_fallas"; no hace
        # falta asumir además que está "inactiva" solo porque no publicó.
        for _ in range(3):
            self.db.registrar_salud_fuente(
                "fuente-a", "error", mensaje_error="fallo", fecha_consulta=_iso(timedelta())
            )

        alertas = calcular_alertas(self.db, ahora=AHORA)

        self.assertFalse(any(a["tipo"] == "fuente_inactiva" for a in alertas))
        self.assertTrue(any(a["tipo"] == "fuente_con_fallas" for a in alertas))


class TestAlertaSinInformacionLocal(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmpdir.name) / "test.db")

    def tearDown(self):
        self.db.close()
        self.tmpdir.cleanup()

    def test_no_hay_alerta_si_hubo_noticia_local_hace_menos_de_6_horas(self):
        self.db.guardar(_noticia_relevante(_iso(timedelta(hours=3))))

        alertas = calcular_alertas(self.db, ahora=AHORA)

        self.assertFalse(any(a["tipo"] == "sin_informacion_local" for a in alertas))

    def test_alerta_tras_6_horas_sin_noticias_locales(self):
        self.db.guardar(_noticia_relevante(_iso(timedelta(hours=7))))

        alertas = calcular_alertas(self.db, ahora=AHORA)

        alertas_locales = [a for a in alertas if a["tipo"] == "sin_informacion_local"]
        self.assertEqual(len(alertas_locales), 1)
        self.assertEqual(alertas_locales[0]["nivel"], "ADVERTENCIA")

    def test_alerta_cuando_nunca_hubo_ninguna_noticia_local(self):
        alertas = calcular_alertas(self.db, ahora=AHORA)

        self.assertTrue(any(a["tipo"] == "sin_informacion_local" for a in alertas))


if __name__ == "__main__":
    unittest.main()
