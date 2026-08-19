import shutil
import subprocess
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts" / "windows"
PWSH = shutil.which("pwsh")


def _leer(nombre: str) -> str:
    return (SCRIPTS_DIR / nombre).read_text(encoding="utf-8-sig")


SCRIPTS_META = (
    "start_meta_programacion.ps1",
    "start_meta_placas.ps1",
    "start_meta_publicar.ps1",
    "start_meta_reintentos.ps1",
    "start_meta_urgentes.ps1",
)


class TestArchivosDeTareasMeta(unittest.TestCase):
    def test_los_cinco_scripts_existen(self):
        for nombre in SCRIPTS_META:
            with self.subTest(nombre=nombre):
                self.assertTrue((SCRIPTS_DIR / nombre).exists(), f"falta {nombre}")

    def test_todos_llevan_bom_utf8(self):
        for nombre in SCRIPTS_META:
            with self.subTest(nombre=nombre):
                crudo = (SCRIPTS_DIR / nombre).read_bytes()
                self.assertTrue(crudo.startswith(b"\xef\xbb\xbf"))

    def test_todos_reutilizan_common(self):
        for nombre in SCRIPTS_META:
            with self.subTest(nombre=nombre):
                self.assertIn("common.ps1", _leer(nombre))

    @unittest.skipUnless(PWSH, "pwsh no disponible en este entorno")
    def test_todos_parsean_sin_errores_con_powershell_real(self):
        for nombre in SCRIPTS_META + (
            "install_tasks.ps1",
            "uninstall_tasks.ps1",
            "status.ps1",
        ):
            with self.subTest(nombre=nombre):
                ruta = SCRIPTS_DIR / nombre
                script = (
                    "$tokens = $null; $errors = $null; "
                    f"[System.Management.Automation.Language.Parser]::ParseFile('{ruta}', "
                    "[ref]$tokens, [ref]$errors) | Out-Null; "
                    "exit $errors.Count"
                )
                resultado = subprocess.run([PWSH, "-NoProfile", "-Command", script])
                self.assertEqual(resultado.returncode, 0, f"{nombre} tiene errores de sintaxis")


TAREAS_META = (
    "LedesmaParticipa-MetaProgramacion",
    "LedesmaParticipa-MetaPlacas",
    "LedesmaParticipa-MetaPublicar",
    "LedesmaParticipa-MetaReintentos",
    "LedesmaParticipa-MetaUrgentes",
)


class TestInstallTasksIncluyeLasTareasDeMeta(unittest.TestCase):
    def test_registra_las_cinco_tareas_nuevas(self):
        contenido = _leer("install_tasks.ps1")
        for tarea in TAREAS_META:
            with self.subTest(tarea=tarea):
                self.assertIn(tarea, contenido)
                self.assertIn(f"Register-ScheduledTask -TaskName ${tarea.replace('LedesmaParticipa-', 'Tarea')}", contenido)

    def test_publicar_tiene_quince_franjas_horarias(self):
        contenido = _leer("install_tasks.ps1")
        horas = ("07:35",) + tuple(f"{h:02d}:00" for h in range(9, 23))
        for hora in horas:
            with self.subTest(hora=hora):
                self.assertIn(hora, contenido)

    def test_no_pisa_las_tareas_existentes(self):
        contenido = _leer("install_tasks.ps1")
        for tarea in ("LedesmaParticipa-Motor", "LedesmaParticipa-Panel", "LedesmaParticipa-InformeDiario"):
            with self.subTest(tarea=tarea):
                self.assertIn(tarea, contenido)


class TestUninstallYStatusIncluyenMeta(unittest.TestCase):
    def test_uninstall_incluye_las_cinco_tareas_de_meta(self):
        contenido = _leer("uninstall_tasks.ps1")
        for tarea in TAREAS_META:
            with self.subTest(tarea=tarea):
                self.assertIn(tarea, contenido)

    def test_uninstall_sigue_sin_tocar_el_proyecto(self):
        contenido = _leer("uninstall_tasks.ps1")
        for patron in ("Remove-Item", "rm ", "del ", "rd "):
            with self.subTest(patron=patron):
                self.assertNotIn(patron, contenido)

    def test_status_reporta_credenciales_de_meta_sin_exponer_valores(self):
        contenido = _leer("status.ps1")
        self.assertIn("META_PAGE_ACCESS_TOKEN", contenido)
        self.assertIn("META_IG_USER_ID", contenido)
        # nunca debe interpolar el valor real de una variable de entorno
        # sensible como texto plano fuera de un chequeo booleano
        self.assertNotIn("Write-Host $env:META_PAGE_ACCESS_TOKEN", contenido)

    def test_status_sigue_siendo_de_solo_lectura(self):
        contenido = _leer("status.ps1")
        for patron in ("Register-ScheduledTask", "Unregister-ScheduledTask", "Remove-Item", "New-Item"):
            with self.subTest(patron=patron):
                self.assertNotIn(patron, contenido)


if __name__ == "__main__":
    unittest.main()
