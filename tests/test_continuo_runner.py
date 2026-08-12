import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from motor_noticias.ciclo_continuo import INTERVALO_SEGUNDOS_DEFAULT, ResumenCiclo
from motor_noticias.continuo_runner import (
    InstanciaEnEjecucion,
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

    def tearDown(self):
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


if __name__ == "__main__":
    unittest.main()
