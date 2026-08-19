import shutil
import subprocess
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts" / "windows"
PWSH = shutil.which("pwsh")


def _leer(nombre: str) -> str:
    return (SCRIPTS_DIR / nombre).read_text(encoding="utf-8-sig")


class TestScriptSitioWebExiste(unittest.TestCase):
    def test_start_sitio_web_existe(self):
        self.assertTrue((SCRIPTS_DIR / "start_sitio_web.ps1").exists())

    def test_lleva_bom_utf8(self):
        crudo = (SCRIPTS_DIR / "start_sitio_web.ps1").read_bytes()
        self.assertTrue(crudo.startswith(b"\xef\xbb\xbf"))

    def test_reutiliza_common(self):
        self.assertIn("common.ps1", _leer("start_sitio_web.ps1"))

    def test_invoca_generar_sitio_web_sin_forzar_redactor(self):
        contenido = _leer("start_sitio_web.ps1")
        self.assertIn("generar_sitio_web.py", contenido)
        linea_invocacion = next(
            l for l in contenido.splitlines() if "generar_sitio_web.py" in l and l.strip().startswith("&")
        )
        self.assertNotIn("--redactor", linea_invocacion)

    @unittest.skipUnless(PWSH, "pwsh no disponible en este entorno")
    def test_parsea_sin_errores_con_powershell_real(self):
        ruta = SCRIPTS_DIR / "start_sitio_web.ps1"
        script = (
            "$tokens = $null; $errors = $null; "
            f"[System.Management.Automation.Language.Parser]::ParseFile('{ruta}', "
            "[ref]$tokens, [ref]$errors) | Out-Null; "
            "exit $errors.Count"
        )
        resultado = subprocess.run([PWSH, "-NoProfile", "-Command", script])
        self.assertEqual(resultado.returncode, 0, "start_sitio_web.ps1 tiene errores de sintaxis")


class TestInstallTasksIncluyeSitioWeb(unittest.TestCase):
    def test_registra_la_tarea(self):
        contenido = _leer("install_tasks.ps1")
        self.assertIn("LedesmaParticipa-SitioWeb", contenido)
        self.assertIn("Register-ScheduledTask -TaskName $TareaSitioWeb", contenido)

    def test_corre_cada_quince_minutos(self):
        contenido = _leer("install_tasks.ps1")
        bloque = contenido.split("$triggerSitioWeb", 1)[1].split("$accionMotor", 1)[0]
        self.assertIn("New-TimeSpan -Minutes 15", bloque)

    def test_reutiliza_settings_y_principal_compartidos(self):
        # Un solo bloque de $settings/$principal en todo el archivo: la
        # tarea de SitioWeb no define uno propio.
        contenido = _leer("install_tasks.ps1")
        self.assertEqual(contenido.count("New-ScheduledTaskSettingsSet"), 1)
        self.assertEqual(contenido.count("New-ScheduledTaskPrincipal"), 1)
        self.assertIn(
            "Register-ScheduledTask -TaskName $TareaSitioWeb -Trigger $triggerSitioWeb -Action $accionSitioWeb "
            "-Settings $settings -Principal $principal -Force",
            contenido,
        )

    def test_no_pisa_las_tareas_existentes(self):
        contenido = _leer("install_tasks.ps1")
        for tarea in (
            "LedesmaParticipa-Motor",
            "LedesmaParticipa-Panel",
            "LedesmaParticipa-InformeDiario",
            "LedesmaParticipa-MetaUrgentes",
        ):
            with self.subTest(tarea=tarea):
                self.assertIn(tarea, contenido)


class TestUninstallYStatusIncluyenSitioWeb(unittest.TestCase):
    def test_uninstall_incluye_la_tarea(self):
        contenido = _leer("uninstall_tasks.ps1")
        self.assertIn("LedesmaParticipa-SitioWeb", contenido)

    def test_uninstall_sigue_sin_tocar_el_proyecto(self):
        contenido = _leer("uninstall_tasks.ps1")
        for patron in ("Remove-Item", "rm ", "del ", "rd "):
            with self.subTest(patron=patron):
                self.assertNotIn(patron, contenido)

    def test_status_reporta_la_tarea_y_sigue_de_solo_lectura(self):
        contenido = _leer("status.ps1")
        self.assertIn("LedesmaParticipa-SitioWeb", contenido)
        self.assertIn("docs\\index.html", contenido)
        prohibidos = (
            "Register-ScheduledTask",
            "Unregister-ScheduledTask",
            "Remove-Item",
            "New-Item",
            "Set-Content",
            "Add-Content",
        )
        for patron in prohibidos:
            with self.subTest(patron=patron):
                self.assertNotIn(patron, contenido)


if __name__ == "__main__":
    unittest.main()
