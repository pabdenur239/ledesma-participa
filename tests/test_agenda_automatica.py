import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from motor_noticias.ciclo_continuo import (
    NOMBRE_SALUD_AGENDA,
    agenda_automatica_habilitada,
    ejecutar_ciclo,
)
from motor_noticias.continuo_runner import bucle_continuo
from motor_noticias.db import Database
from motor_noticias.motor_editorial import ZONA_JUJUY, generar_agenda
from motor_noticias.redaccion.mock import RedactorMock

from tests.test_ciclo_continuo import (
    NOTICIA_LOCAL,
    ErrorFuenteDePrueba,
    _colector_error,
    _colector_ok,
    _cruda,
)
from tests.test_motor_editorial import AHORA, _crear_noticia

REPO_ROOT = Path(__file__).resolve().parent.parent

# Este módulo llama a `bucle_continuo` directamente (no solo a `ejecutar_ciclo`),
# y `bucle_continuo` ahora también dispara `_ejecutar_publicacion_y_sitio` en
# cada ciclo (publicaría de verdad en Meta con el token real de esta
# notebook, y haría git commit/push contra el repo real). Se mockea para
# todo el módulo: ningún test de acá prueba esa integración (eso vive en
# tests/test_continuo_runner.py), así que nunca debe tener ese efecto real.
def setUpModule():
    global _parche_publicacion_y_sitio
    _parche_publicacion_y_sitio = patch("motor_noticias.continuo_runner._ejecutar_publicacion_y_sitio")
    _parche_publicacion_y_sitio.start()


def tearDownModule():
    _parche_publicacion_y_sitio.stop()


class BaseCicloTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmpdir.name) / "test.db")
        self.redactor = RedactorMock()

    def tearDown(self):
        self.db.close()
        self.tmpdir.cleanup()


# 1. ciclo continuo actualiza agenda
class TestCicloActualizaAgenda(BaseCicloTest):
    def test_ciclo_continuo_actualiza_agenda(self):
        fuentes_prueba = (("fuente-a", _colector_ok([NOTICIA_LOCAL]), ErrorFuenteDePrueba),)
        with patch("motor_noticias.ciclo_continuo.FUENTES_CONTINUAS", fuentes_prueba):
            resumen = ejecutar_ciclo(self.db, self.redactor)

        self.assertTrue(resumen.agenda_actualizada)
        salud_agenda = self.db.obtener_salud_fuente(NOMBRE_SALUD_AGENDA)
        self.assertEqual(salud_agenda["ultimo_resultado"], "ok")
        # Alguna franja del día quedó con la noticia local recolectada o al
        # menos evaluada (agenda_item existe para hoy en Jujuy).
        hoy = datetime.now(ZONA_JUJUY).strftime("%Y-%m-%d")
        self.assertTrue(self.db.listar_agenda(hoy))

    # 2. agenda se actualiza después de consultar todas las fuentes
    def test_agenda_se_actualiza_despues_de_todas_las_fuentes(self):
        orden = []

        def _colector_que_registra(nombre, items):
            class _ColectorDePrueba:
                def recolectar(self):
                    orden.append(f"fuente:{nombre}")
                    return items

            return _ColectorDePrueba

        fuentes_prueba = (
            ("fuente-a", _colector_que_registra("fuente-a", [NOTICIA_LOCAL]), ErrorFuenteDePrueba),
            ("fuente-b", _colector_que_registra("fuente-b", []), ErrorFuenteDePrueba),
        )

        generar_agenda_real = generar_agenda

        def _generar_agenda_que_registra(db, *args, **kwargs):
            orden.append("agenda")
            return generar_agenda_real(db, *args, **kwargs)

        with patch("motor_noticias.ciclo_continuo.FUENTES_CONTINUAS", fuentes_prueba), patch(
            "motor_noticias.ciclo_continuo.generar_agenda", side_effect=_generar_agenda_que_registra
        ):
            ejecutar_ciclo(self.db, self.redactor)

        self.assertEqual(orden, ["fuente:fuente-a", "fuente:fuente-b", "agenda"])

    # 3. fuente fallida no impide actualizar agenda
    def test_fuente_fallida_no_impide_actualizar_agenda(self):
        fuentes_prueba = (
            ("fuente-a", _colector_ok([NOTICIA_LOCAL]), ErrorFuenteDePrueba),
            ("fuente-rota", _colector_error("fallo simulado"), ErrorFuenteDePrueba),
        )
        with patch("motor_noticias.ciclo_continuo.FUENTES_CONTINUAS", fuentes_prueba):
            resumen = ejecutar_ciclo(self.db, self.redactor)

        self.assertEqual(resumen.total_errores, 1)
        self.assertTrue(resumen.agenda_actualizada)
        self.assertEqual(self.db.obtener_salud_fuente(NOMBRE_SALUD_AGENDA)["ultimo_resultado"], "ok")

    # 4. agenda fallida no detiene motor continuo
    def test_agenda_fallida_no_detiene_ciclo_continuo(self):
        fuentes_prueba = (("fuente-a", _colector_ok([NOTICIA_LOCAL]), ErrorFuenteDePrueba),)
        with patch("motor_noticias.ciclo_continuo.FUENTES_CONTINUAS", fuentes_prueba), patch(
            "motor_noticias.ciclo_continuo.generar_agenda", side_effect=RuntimeError("boom")
        ):
            resumen = ejecutar_ciclo(self.db, self.redactor)

        self.assertFalse(resumen.agenda_actualizada)
        self.assertIn("boom", resumen.agenda_mensaje_error)
        self.assertEqual(len(resumen.resultados), 1)
        self.assertEqual(resumen.resultados[0].resultado, "ok")
        salud_agenda = self.db.obtener_salud_fuente(NOMBRE_SALUD_AGENDA)
        self.assertEqual(salud_agenda["ultimo_resultado"], "error")
        self.assertIn("boom", salud_agenda["ultimo_error"])
        # el ciclo se registró igual, no se interrumpió
        self.assertIsNotNone(self.db.ultimo_ciclo())

        # y una ronda siguiente (ya sin el fallo) sigue funcionando
        with patch("motor_noticias.ciclo_continuo.FUENTES_CONTINUAS", fuentes_prueba):
            resumen2 = ejecutar_ciclo(self.db, self.redactor)
        self.assertTrue(resumen2.agenda_actualizada)

    # 13. primera ejecución genera agenda inmediatamente (no espera el intervalo)
    def test_primera_ejecucion_genera_agenda_inmediatamente(self):
        fuentes_prueba = (("fuente-a", _colector_ok([NOTICIA_LOCAL]), ErrorFuenteDePrueba),)
        dormidas = []
        with patch("motor_noticias.ciclo_continuo.FUENTES_CONTINUAS", fuentes_prueba):
            bucle_continuo(self.db, self.redactor, intervalo_segundos=1800, max_ciclos=1, dormir=dormidas.append)

        # ni siquiera se llegó a "dormir": el único ciclo ya corrió y generó agenda.
        self.assertEqual(dormidas, [])
        hoy = datetime.now(ZONA_JUJUY).strftime("%Y-%m-%d")
        self.assertTrue(self.db.listar_agenda(hoy))
        self.assertEqual(self.db.obtener_salud_fuente(NOMBRE_SALUD_AGENDA)["ultimo_resultado"], "ok")

    # 14. segunda ejecución idéntica no genera cambios innecesarios
    def test_segunda_ejecucion_identica_no_genera_cambios_innecesarios(self):
        fuentes_prueba = (("fuente-a", _colector_ok([NOTICIA_LOCAL]), ErrorFuenteDePrueba),)
        with patch("motor_noticias.ciclo_continuo.FUENTES_CONTINUAS", fuentes_prueba):
            ejecutar_ciclo(self.db, self.redactor)
            hoy = datetime.now(ZONA_JUJUY).strftime("%Y-%m-%d")
            items_antes = {(i["hora"], i["tipo"]): i["actualizada_en"] for i in self.db.listar_agenda(hoy)}

            ejecutar_ciclo(self.db, self.redactor)
            items_despues = {(i["hora"], i["tipo"]): i["actualizada_en"] for i in self.db.listar_agenda(hoy)}

        self.assertEqual(items_antes, items_despues)

    # 15. urgente nueva aparece una sola vez
    def test_urgente_nueva_aparece_una_sola_vez(self):
        urgente = _cruda("Alerta urgente en Libertador General San Martín por corte de agua")
        fuentes_prueba = (("fuente-a", _colector_ok([urgente]), ErrorFuenteDePrueba),)
        # Se recolecta primero sin tocar la agenda todavía, para poder marcar
        # la noticia como urgente antes de que un ciclo la tome como
        # candidata "normal" de una franja (lo que la dejaría "usada" y ya
        # no elegible como propuesta urgente aparte).
        with patch("motor_noticias.ciclo_continuo.FUENTES_CONTINUAS", fuentes_prueba):
            ejecutar_ciclo(self.db, self.redactor, agenda_automatica=False)

        noticias = self.db.listar()
        self.assertEqual(len(noticias), 1)
        self.db.marcar_urgente(noticias[0]["id"], True)

        with patch("motor_noticias.ciclo_continuo.FUENTES_CONTINUAS", fuentes_prueba):
            ejecutar_ciclo(self.db, self.redactor)  # primera actualización de agenda con la urgente ya marcada
            ejecutar_ciclo(self.db, self.redactor)  # segunda ronda: no debe duplicarla

        hoy = datetime.now(ZONA_JUJUY).strftime("%Y-%m-%d")
        urgentes = [i for i in self.db.listar_agenda(hoy) if i["tipo"] == "urgente"]
        self.assertEqual(len(urgentes), 1)

    # 16. agenda automática puede desactivarse
    def test_agenda_automatica_puede_desactivarse(self):
        fuentes_prueba = (("fuente-a", _colector_ok([NOTICIA_LOCAL]), ErrorFuenteDePrueba),)
        with patch("motor_noticias.ciclo_continuo.FUENTES_CONTINUAS", fuentes_prueba):
            resumen = ejecutar_ciclo(self.db, self.redactor, agenda_automatica=False)

        self.assertIsNone(resumen.agenda_actualizada)
        self.assertIsNone(self.db.obtener_salud_fuente(NOMBRE_SALUD_AGENDA))
        hoy = datetime.now(ZONA_JUJUY).strftime("%Y-%m-%d")
        self.assertEqual(self.db.listar_agenda(hoy), [])
        # las fuentes sí se procesaron igual: el motor sigue funcionando
        self.assertEqual(len(self.db.listar()), 1)

    def test_flag_agenda_automatica_se_lee_de_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "agenda.json"
            config_path.write_text('{"agenda_automatica": false}', encoding="utf-8")
            self.assertFalse(agenda_automatica_habilitada(config_path))

            config_path.write_text('{"agenda_automatica": true}', encoding="utf-8")
            self.assertTrue(agenda_automatica_habilitada(config_path))

        # archivo inexistente → default true, sin crear configuración compleja
        self.assertTrue(agenda_automatica_habilitada(Path(tmp) / "no-existe.json"))


class BaseAgendaFranjasTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmpdir.name) / "test.db")

    def tearDown(self):
        self.db.close()
        self.tmpdir.cleanup()


class TestFranjasTemporales(BaseAgendaFranjasTest):
    # 5. sin_candidato futuro pasa a pendiente
    def test_sin_candidato_futuro_pasa_a_pendiente(self):
        entradas_antes = generar_agenda(self.db, fecha="2026-08-12", horarios=("10:30",), ahora=AHORA)
        self.assertEqual(entradas_antes[0].estado, "sin_candidato")

        _crear_noticia(self.db, "local")

        entradas_despues = generar_agenda(self.db, fecha="2026-08-12", horarios=("10:30",), ahora=AHORA)
        self.assertEqual(entradas_despues[0].estado, "actualizado")
        self.assertIsNotNone(entradas_despues[0].noticia_id)

    # 6. pendiente provincial futura reemplazada por local
    def test_pendiente_provincial_futura_reemplazada_por_local(self):
        provincial = _crear_noticia(self.db, "provincial", fecha_recoleccion=_iso(timedelta(hours=2)))
        generar_agenda(self.db, fecha="2026-08-12", horarios=("10:30",), ahora=AHORA)

        local = _crear_noticia(self.db, "local", fecha_recoleccion=_iso())
        entradas = generar_agenda(self.db, fecha="2026-08-12", horarios=("10:30",), ahora=AHORA)

        self.assertEqual(entradas[0].noticia_id, local.id)
        self.assertEqual(entradas[0].territorio, "local")
        self.assertNotEqual(entradas[0].noticia_id, provincial.id)

    # 7. franja pasada no recibe nuevo candidato
    def test_franja_pasada_no_recibe_nuevo_candidato(self):
        # 08:00 Jujuy ya pasó respecto de AHORA (09:00 Jujuy): queda sin
        # candidato "congelada" aunque después aparezca una noticia válida.
        entradas_antes = generar_agenda(self.db, fecha="2026-08-12", horarios=("08:00",), ahora=AHORA)
        self.assertEqual(entradas_antes[0].estado, "sin_candidato")

        _crear_noticia(self.db, "local")

        entradas_despues = generar_agenda(self.db, fecha="2026-08-12", horarios=("08:00",), ahora=AHORA)
        self.assertEqual(entradas_despues[0].estado, "sin_candidato")
        self.assertIsNone(entradas_despues[0].noticia_id)

    # 8. franja pasada pendiente no se reemplaza
    def test_franja_pasada_pendiente_no_se_reemplaza(self):
        provincial = _crear_noticia(self.db, "provincial", fecha_recoleccion=_iso(timedelta(hours=2)))
        # 08:00 Jujuy ya pasó respecto de AHORA (09:00 Jujuy).
        generar_agenda(self.db, fecha="2026-08-12", horarios=("08:00",), ahora=AHORA)
        item_antes = self.db.obtener_agenda_item("2026-08-12", "08:00")
        self.assertEqual(item_antes["noticia_id"], provincial.id)

        _crear_noticia(self.db, "local", fecha_recoleccion=_iso())  # mejor candidato, llega tarde

        entradas = generar_agenda(self.db, fecha="2026-08-12", horarios=("08:00",), ahora=AHORA)
        self.assertEqual(entradas[0].noticia_id, provincial.id)  # no se reemplaza retroactivamente
        self.assertEqual(entradas[0].estado, "existente")

    # 9. aprobada no se modifica
    def test_aprobada_no_se_modifica(self):
        provincial = _crear_noticia(self.db, "provincial", fecha_recoleccion=_iso(timedelta(hours=2)))
        generar_agenda(self.db, fecha="2026-08-12", horarios=("10:30",), ahora=AHORA)
        item = self.db.obtener_agenda_item("2026-08-12", "10:30")
        self.db.actualizar_revision(item["noticia_id"], "aprobada")

        _crear_noticia(self.db, "local", fecha_recoleccion=_iso())
        entradas = generar_agenda(self.db, fecha="2026-08-12", horarios=("10:30",), ahora=AHORA)

        self.assertEqual(entradas[0].noticia_id, provincial.id)
        self.assertEqual(entradas[0].estado, "existente")

    # 10. rechazada no se modifica
    def test_rechazada_no_se_modifica(self):
        provincial = _crear_noticia(self.db, "provincial", fecha_recoleccion=_iso(timedelta(hours=2)))
        generar_agenda(self.db, fecha="2026-08-12", horarios=("10:30",), ahora=AHORA)
        item = self.db.obtener_agenda_item("2026-08-12", "10:30")
        self.db.actualizar_revision(item["noticia_id"], "rechazada")

        _crear_noticia(self.db, "local", fecha_recoleccion=_iso())
        entradas = generar_agenda(self.db, fecha="2026-08-12", horarios=("10:30",), ahora=AHORA)

        self.assertEqual(entradas[0].noticia_id, provincial.id)
        self.assertEqual(entradas[0].estado, "existente")

    # 11. publicada no se modifica
    def test_publicada_no_se_modifica(self):
        from motor_noticias.models import Estado

        publicada = _crear_noticia(
            self.db, "provincial", fecha_recoleccion=_iso(timedelta(hours=2)), estado=Estado.PUBLICADA.value
        )
        creada_en = _iso(timedelta(hours=2))
        self.db.guardar_agenda_item("2026-08-12", "10:30", "normal", "provincial", publicada.id, creada_en)

        _crear_noticia(self.db, "local", fecha_recoleccion=_iso())
        entradas = generar_agenda(self.db, fecha="2026-08-12", horarios=("10:30",), ahora=AHORA)

        self.assertEqual(entradas[0].noticia_id, publicada.id)
        self.assertEqual(entradas[0].estado, "existente")

    # 12. noticia llegada después de una franja compite por la siguiente
    def test_noticia_llegada_despues_de_franja_compite_por_siguiente(self):
        provincial = _crear_noticia(self.db, "provincial", fecha_recoleccion=_iso(timedelta(hours=2)))
        # A las 09:30 Jujuy (AHORA), 10:30 es futura: la provincial la ocupa.
        entradas_1030 = generar_agenda(self.db, fecha="2026-08-12", horarios=("10:30",), ahora=AHORA)
        self.assertEqual(entradas_1030[0].noticia_id, provincial.id)

        # A las 11:45 Jujuy, 10:30 ya pasó: no se toca retroactivamente.
        despues_de_1030 = AHORA + timedelta(hours=2, minutes=45)  # 09:00 + 2:45 = 11:45 Jujuy
        local = _crear_noticia(self.db, "local", fecha_recoleccion=_iso())

        entradas_congelada = generar_agenda(
            self.db, fecha="2026-08-12", horarios=("10:30",), ahora=despues_de_1030
        )
        self.assertEqual(entradas_congelada[0].noticia_id, provincial.id)
        self.assertEqual(entradas_congelada[0].estado, "existente")

        # Pero la noticia local sí compite y gana la próxima franja disponible.
        entradas_1300 = generar_agenda(self.db, fecha="2026-08-12", horarios=("13:00",), ahora=despues_de_1030)
        self.assertEqual(entradas_1300[0].noticia_id, local.id)
        self.assertEqual(entradas_1300[0].territorio, "local")

    # 17. timezone Jujuy (UTC-3 fija) determina franja pasada/futura
    def test_timezone_jujuy_determina_franja_pasada(self):
        from motor_noticias.motor_editorial import _es_franja_pasada

        # AHORA = 2026-08-12 12:00 UTC = 2026-08-12 09:00 Jujuy (UTC-3).
        self.assertTrue(_es_franja_pasada("2026-08-12", "08:00", AHORA))
        self.assertTrue(_es_franja_pasada("2026-08-12", "09:00", AHORA))  # exactamente ahora: pasada
        self.assertFalse(_es_franja_pasada("2026-08-12", "10:30", AHORA))


def _iso(delta: timedelta = timedelta()) -> str:
    return (AHORA - delta).isoformat()


class TestPanelMuestraEstadoAgenda(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmpdir.name) / "test.db")

    def tearDown(self):
        self.db.close()
        self.tmpdir.cleanup()

    # 18. panel muestra estado de agenda automática
    def test_panel_estado_muestra_seccion_agenda_automatica(self):
        from motor_noticias.panel.server import _estado_sistema_html

        self.db.registrar_salud_fuente(NOMBRE_SALUD_AGENDA, "ok", elementos_obtenidos=6, noticias_nuevas=2)

        html = _estado_sistema_html(self.db, Path(self.tmpdir.name) / "no-existe.lock")

        self.assertIn("Agenda Editorial automática", html)
        self.assertIn("Agenda automática", html)
        self.assertIn("Próxima franja prevista", html)
        self.assertIn("Espacios pendientes", html)


class TestCliManualGenerarAgenda(unittest.TestCase):
    # 19. generar_agenda.py manual sigue funcionando
    def test_generar_agenda_cli_sigue_funcionando(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "manual.db"
            db = Database(db_path)
            _crear_noticia(db, "local")
            db.close()

            resultado = subprocess.run(
                [sys.executable, "generar_agenda.py", "--db", str(db_path), "--fecha", "2026-08-12"],
                cwd=str(REPO_ROOT),
                capture_output=True,
                text=True,
                timeout=30,
            )

        self.assertEqual(resultado.returncode, 0, resultado.stderr)
        self.assertIn("Agenda editorial", resultado.stdout)
        self.assertIn("2026-08-12", resultado.stdout)


if __name__ == "__main__":
    unittest.main()
