import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from motor_noticias.ciclo_continuo import INTERVALO_SEGUNDOS_DEFAULT, ResumenCiclo
from motor_noticias.continuo_runner import (
    NOMBRE_SCRIPT_LOCK,
    InstanciaEnEjecucion,
    _leer_lock,
    _proceso_activo,
    bucle_continuo,
    construir_parser,
    liberar_lock,
    tomar_lock,
)
from motor_noticias.db import Database
from motor_noticias.redaccion.mock import RedactorMock

RESUMEN_CICLO_FALSO = ResumenCiclo(
    fecha_inicio="2026-08-12T00:00:00+00:00",
    fecha_fin="2026-08-12T00:00:01+00:00",
    resultados=[],
    total_noticias_nuevas=0,
    total_errores=0,
)


class TestLockDeInstanciaUnica(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.lock_path = Path(self.tmpdir.name) / "run_continuo.lock"

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_tomar_lock_crea_el_archivo(self):
        tomar_lock(self.lock_path)
        self.assertTrue(self.lock_path.exists())

    def test_tomar_lock_dos_veces_falla(self):
        tomar_lock(self.lock_path)
        with self.assertRaises(InstanciaEnEjecucion):
            tomar_lock(self.lock_path)

    def test_liberar_lock_permite_tomarlo_de_nuevo(self):
        tomar_lock(self.lock_path)
        liberar_lock(self.lock_path)
        self.assertFalse(self.lock_path.exists())
        tomar_lock(self.lock_path)  # no debe fallar
        self.assertTrue(self.lock_path.exists())

    def test_liberar_lock_sin_haberlo_tomado_no_falla(self):
        liberar_lock(self.lock_path)  # no debe lanzar excepción

    def test_lock_nuevo_contiene_pid_script_y_timestamp(self):
        tomar_lock(self.lock_path)

        datos = json.loads(self.lock_path.read_text(encoding="utf-8"))
        self.assertEqual(datos["pid"], os.getpid())
        self.assertEqual(datos["script"], NOMBRE_SCRIPT_LOCK)
        self.assertIn("iniciado_en", datos)

    def test_proceso_activo_real_detecta_el_propio_proceso(self):
        # Único caso no-flaky de probar la implementación real (sin
        # inyectar nada): el proceso que corre el test seguro está vivo.
        self.assertTrue(_proceso_activo(os.getpid()))

    def test_proceso_activo_real_devuelve_false_para_pid_invalido(self):
        self.assertFalse(_proceso_activo(0))
        self.assertFalse(_proceso_activo(-1))


class TestLockActivoObsoletoEInvalido(unittest.TestCase):
    """Bug real: tras un apagado inesperado, run_continuo.py se negaba a
    arrancar por un lock cuyo proceso dueño ya no existía. tomar_lock ahora
    distingue lock activo (bloquea de verdad) de lock obsoleto/inválido (se
    limpia solo y continúa), usando `proceso_activo` inyectable para que
    la decisión sea 100% testeable sin depender del SO real."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.lock_path = Path(self.tmpdir.name) / "run_continuo.lock"

    def tearDown(self):
        self.tmpdir.cleanup()

    # --- lock activo: nunca se debe eliminar ---
    def test_lock_con_proceso_realmente_activo_bloquea(self):
        pid_ajeno = os.getpid() + 1  # cualquier PID distinto del propio
        self.lock_path.write_text(
            json.dumps({"pid": pid_ajeno, "script": NOMBRE_SCRIPT_LOCK}), encoding="utf-8"
        )

        with self.assertRaises(InstanciaEnEjecucion):
            tomar_lock(self.lock_path, proceso_activo=lambda pid: True)

        # el lock del proceso activo se conserva intacto, no se borra
        self.assertTrue(self.lock_path.exists())
        self.assertEqual(json.loads(self.lock_path.read_text(encoding="utf-8"))["pid"], pid_ajeno)

    def test_mensaje_de_error_incluye_el_pid_activo(self):
        pid_ajeno = 424242
        self.lock_path.write_text(json.dumps({"pid": pid_ajeno}), encoding="utf-8")

        with self.assertRaises(InstanciaEnEjecucion) as contexto:
            tomar_lock(self.lock_path, proceso_activo=lambda pid: True)
        self.assertIn(str(pid_ajeno), str(contexto.exception))

    # --- lock obsoleto: proceso dueño ya no existe ---
    def test_lock_obsoleto_con_proceso_muerto_se_limpia_y_continua(self):
        pid_viejo = 999999
        self.lock_path.write_text(json.dumps({"pid": pid_viejo, "script": NOMBRE_SCRIPT_LOCK}), encoding="utf-8")

        tomar_lock(self.lock_path, proceso_activo=lambda pid: False)  # no debe lanzar

        # el lock quedó tomado por ESTE proceso, no por el viejo
        datos = json.loads(self.lock_path.read_text(encoding="utf-8"))
        self.assertEqual(datos["pid"], os.getpid())
        self.assertNotEqual(datos["pid"], pid_viejo)

    def test_compatibilidad_lock_viejo_de_solo_pid_activo(self):
        # Formato anterior: el archivo solo contenía el PID como texto.
        pid_ajeno = os.getpid() + 1
        self.lock_path.write_text(str(pid_ajeno), encoding="utf-8")

        with self.assertRaises(InstanciaEnEjecucion):
            tomar_lock(self.lock_path, proceso_activo=lambda pid: True)

    def test_compatibilidad_lock_viejo_de_solo_pid_obsoleto(self):
        self.lock_path.write_text("999999", encoding="utf-8")

        tomar_lock(self.lock_path, proceso_activo=lambda pid: False)  # no debe lanzar
        self.assertEqual(json.loads(self.lock_path.read_text(encoding="utf-8"))["pid"], os.getpid())

    # --- lock inválido: contenido corrupto/vacío/sin pid legible ---
    def test_lock_vacio_se_limpia_y_continua(self):
        self.lock_path.write_text("", encoding="utf-8")

        tomar_lock(self.lock_path)  # no debe lanzar, sin importar proceso_activo

        self.assertEqual(json.loads(self.lock_path.read_text(encoding="utf-8"))["pid"], os.getpid())

    def test_lock_con_contenido_corrupto_se_limpia_y_continua(self):
        self.lock_path.write_text("{esto no es json valido", encoding="utf-8")

        tomar_lock(self.lock_path)  # no debe lanzar

        self.assertEqual(json.loads(self.lock_path.read_text(encoding="utf-8"))["pid"], os.getpid())

    def test_lock_json_sin_pid_se_considera_invalido(self):
        self.lock_path.write_text(json.dumps({"script": NOMBRE_SCRIPT_LOCK}), encoding="utf-8")

        self.assertIsNone(_leer_lock(self.lock_path))
        tomar_lock(self.lock_path)  # no debe lanzar

    def test_lock_json_con_pid_no_numerico_se_considera_invalido(self):
        self.lock_path.write_text(json.dumps({"pid": "no-es-un-numero"}), encoding="utf-8")

        self.assertIsNone(_leer_lock(self.lock_path))
        tomar_lock(self.lock_path)  # no debe lanzar

    def test_condicion_de_carrera_real_al_reintentar_sigue_bloqueando(self):
        # El lock parece obsoleto (proceso muerto), pero justo entre el
        # borrado y el reintento otra instancia real vuelve a tomarlo:
        # nunca debe sobreescribirse a ciegas.
        pid_viejo = 999999
        self.lock_path.write_text(json.dumps({"pid": pid_viejo}), encoding="utf-8")

        def _proceso_activo_falso(pid):
            return False

        with patch("motor_noticias.continuo_runner._escribir_lock") as escribir_mock:
            escribir_mock.side_effect = [FileExistsError(), FileExistsError()]
            with self.assertRaises(InstanciaEnEjecucion):
                tomar_lock(self.lock_path, proceso_activo=_proceso_activo_falso)


class TestConfiguracionDeIntervalo(unittest.TestCase):
    def test_intervalo_por_defecto_es_1800(self):
        self.assertEqual(INTERVALO_SEGUNDOS_DEFAULT, 1800)

    def test_intervalo_configurable_por_argumento(self):
        args = construir_parser().parse_args(["--intervalo", "60"])
        self.assertEqual(args.intervalo, 60)

    def test_intervalo_usa_default_si_no_se_especifica(self):
        args = construir_parser().parse_args([])
        self.assertEqual(args.intervalo, INTERVALO_SEGUNDOS_DEFAULT)


class TestBucleContinuo(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmpdir.name) / "test.db")
        self.redactor = RedactorMock()
        # `bucle_continuo` ahora también dispara `_ejecutar_publicacion_y_sitio`
        # en cada ciclo (publica urgentes/reintentos reales en Meta y hace
        # git commit/push del sitio contra el repo real): se mockea acá para
        # que ningún test de este bloque tenga jamás ese efecto de lado real,
        # salvo los que explícitamente lo estén probando más abajo.
        self.publicacion_y_sitio_patch = patch("motor_noticias.continuo_runner._ejecutar_publicacion_y_sitio")
        self.publicacion_y_sitio_mock = self.publicacion_y_sitio_patch.start()

    def tearDown(self):
        self.publicacion_y_sitio_patch.stop()
        self.db.close()
        self.tmpdir.cleanup()

    @patch("motor_noticias.continuo_runner.ejecutar_ciclo", return_value=RESUMEN_CICLO_FALSO)
    def test_ejecuta_un_ciclo_inmediatamente_y_luego_espera_el_intervalo(self, ejecutar_ciclo_mock):
        dormir = MagicMock(side_effect=KeyboardInterrupt)

        bucle_continuo(self.db, self.redactor, intervalo_segundos=45, dormir=dormir)

        # el primer ciclo ya corrió antes de la primera espera
        ejecutar_ciclo_mock.assert_called_once()
        dormir.assert_called_once_with(45)

    @patch("motor_noticias.continuo_runner.ejecutar_ciclo", return_value=RESUMEN_CICLO_FALSO)
    def test_max_ciclos_detiene_el_bucle_sin_ctrl_c(self, ejecutar_ciclo_mock):
        dormir = MagicMock()

        bucle_continuo(self.db, self.redactor, intervalo_segundos=1, max_ciclos=2, dormir=dormir)

        self.assertEqual(ejecutar_ciclo_mock.call_count, 2)
        self.assertEqual(dormir.call_count, 1)  # duerme entre el ciclo 1 y el 2, no después del 2

    @patch("motor_noticias.continuo_runner.ejecutar_ciclo", return_value=RESUMEN_CICLO_FALSO)
    def test_ctrl_c_durante_la_espera_no_propaga_la_excepcion(self, ejecutar_ciclo_mock):
        dormir = MagicMock(side_effect=KeyboardInterrupt)

        try:
            bucle_continuo(self.db, self.redactor, intervalo_segundos=30, dormir=dormir)
        except KeyboardInterrupt:
            self.fail("bucle_continuo debe manejar Ctrl+C internamente, no propagarlo")

    @patch("motor_noticias.continuo_runner.ejecutar_ciclo", return_value=RESUMEN_CICLO_FALSO)
    def test_cada_ciclo_dispara_tambien_publicacion_y_sitio(self, ejecutar_ciclo_mock):
        # Bug real corregido: MetaUrgentes/MetaReintentos/SitioWeb dependían
        # solo de triggers repetitivos de Task Scheduler, que no sobreviven
        # una suspensión larga de la notebook. El Motor Continuo (proceso
        # persistente que sí demostró resistirlo) ahora dispara ese mismo
        # trabajo como respaldo en cada ciclo.
        dormir = MagicMock(side_effect=KeyboardInterrupt)

        bucle_continuo(self.db, self.redactor, intervalo_segundos=45, dormir=dormir)

        self.publicacion_y_sitio_mock.assert_called_once_with(self.db)

    @patch("motor_noticias.continuo_runner.ejecutar_ciclo", return_value=RESUMEN_CICLO_FALSO)
    def test_un_fallo_en_publicacion_y_sitio_no_interrumpe_el_bucle(self, ejecutar_ciclo_mock):
        self.publicacion_y_sitio_mock.side_effect = RuntimeError("boom")
        dormir = MagicMock(side_effect=KeyboardInterrupt)

        try:
            bucle_continuo(self.db, self.redactor, intervalo_segundos=45, dormir=dormir)
        except RuntimeError:
            self.fail("un fallo en _ejecutar_publicacion_y_sitio no debe tumbar el Motor Continuo")


class TestEjecutarPublicacionYSitio(unittest.TestCase):
    """Cobertura aislada de `_ejecutar_publicacion_y_sitio` y sus dos pasos
    (`_publicar_pendientes_meta`, `_actualizar_sitio_web`): todo mockeado,
    nunca toca Meta real ni el repo git real."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmpdir.name) / "test.db")

    def tearDown(self):
        self.db.close()
        self.tmpdir.cleanup()

    @patch("motor_noticias.continuo_runner._actualizar_sitio_web")
    @patch("motor_noticias.continuo_runner._publicar_pendientes_meta")
    @patch("motor_noticias.continuo_runner.publicacion_meta_automatica_habilitada", return_value=True)
    def test_habilitada_ejecuta_ambos_pasos(self, _habilitada_mock, publicar_mock, sitio_mock):
        from motor_noticias.continuo_runner import _ejecutar_publicacion_y_sitio

        _ejecutar_publicacion_y_sitio(self.db)

        publicar_mock.assert_called_once()
        sitio_mock.assert_called_once_with(self.db.path)

    @patch("motor_noticias.continuo_runner._actualizar_sitio_web")
    @patch("motor_noticias.continuo_runner._publicar_pendientes_meta")
    @patch("motor_noticias.continuo_runner.publicacion_meta_automatica_habilitada", return_value=False)
    def test_deshabilitada_por_configuracion_no_hace_nada(self, _habilitada_mock, publicar_mock, sitio_mock):
        from motor_noticias.continuo_runner import _ejecutar_publicacion_y_sitio

        _ejecutar_publicacion_y_sitio(self.db)

        publicar_mock.assert_not_called()
        sitio_mock.assert_not_called()

    @patch("motor_noticias.continuo_runner.reintentar_publicaciones")
    @patch("motor_noticias.continuo_runner.publicar_urgentes")
    def test_publicar_pendientes_meta_usa_max_pendientes_uno(self, publicar_urgentes_mock, reintentar_mock):
        from motor_noticias.continuo_runner import _publicar_pendientes_meta

        _publicar_pendientes_meta(self.db, "2026-08-19")

        self.assertEqual(publicar_urgentes_mock.call_args.kwargs["max_pendientes"], 1)
        self.assertEqual(reintentar_mock.call_args.kwargs["max_pendientes"], 1)

    @patch("motor_noticias.continuo_runner.reintentar_publicaciones")
    @patch("motor_noticias.continuo_runner.publicar_urgentes")
    def test_publicar_pendientes_meta_un_fallo_en_urgentes_no_impide_reintentos(
        self, publicar_urgentes_mock, reintentar_mock
    ):
        from motor_noticias.continuo_runner import _publicar_pendientes_meta

        publicar_urgentes_mock.side_effect = RuntimeError("boom")

        _publicar_pendientes_meta(self.db, "2026-08-19")  # no debe lanzar

        reintentar_mock.assert_called_once()

    @patch("motor_noticias.continuo_runner.desplegar_sitio")
    @patch("motor_noticias.continuo_runner.generar_sitio")
    @patch("motor_noticias.continuo_runner.deploy_automatico_habilitado", return_value=True)
    def test_actualizar_sitio_web_regenera_y_despliega(self, _habilitado_mock, generar_mock, desplegar_mock):
        from motor_noticias.continuo_runner import _actualizar_sitio_web
        from motor_noticias.sitio.deploy import ResultadoDeploy

        desplegar_mock.return_value = ResultadoDeploy("desplegado")

        _actualizar_sitio_web(self.db.path)

        generar_mock.assert_called_once()
        desplegar_mock.assert_called_once()

    @patch("motor_noticias.continuo_runner.desplegar_sitio")
    @patch("motor_noticias.continuo_runner.generar_sitio")
    @patch("motor_noticias.continuo_runner.deploy_automatico_habilitado", return_value=False)
    def test_actualizar_sitio_web_deploy_deshabilitado_no_llama_git(
        self, _habilitado_mock, generar_mock, desplegar_mock
    ):
        from motor_noticias.continuo_runner import _actualizar_sitio_web

        _actualizar_sitio_web(self.db.path)

        generar_mock.assert_called_once()
        desplegar_mock.assert_not_called()

    @patch("motor_noticias.continuo_runner.desplegar_sitio")
    @patch("motor_noticias.continuo_runner.generar_sitio")
    def test_actualizar_sitio_web_fallo_de_generacion_no_intenta_desplegar(self, generar_mock, desplegar_mock):
        from motor_noticias.continuo_runner import _actualizar_sitio_web

        generar_mock.side_effect = RuntimeError("boom")

        _actualizar_sitio_web(self.db.path)  # no debe lanzar

        desplegar_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
