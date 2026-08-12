"""Tests offline de los scripts de producción Windows (scripts/windows/).

No se ejecuta PowerShell en ningún momento (no está disponible fuera de
Windows): se valida el CONTENIDO de los .ps1 — rutas resueltas dinámicamente,
configuración compartida (no duplicada), nombres/trigger de las tareas,
ausencia de contraseñas/secretos, bind exclusivo a 127.0.0.1, y que
status.ps1/uninstall_tasks.ps1 sean seguros (solo lectura / alcance acotado).
"""
import re
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts" / "windows"


def _leer(nombre: str) -> str:
    return (SCRIPTS_DIR / nombre).read_text(encoding="utf-8")


class TestArchivosExisten(unittest.TestCase):
    def test_scripts_minimos_existen(self):
        for nombre in (
            "common.ps1",
            "check_ollama.ps1",
            "start_motor.ps1",
            "start_panel.ps1",
            "install_tasks.ps1",
            "uninstall_tasks.ps1",
            "status.ps1",
        ):
            with self.subTest(nombre=nombre):
                self.assertTrue((SCRIPTS_DIR / nombre).exists(), f"falta {nombre}")


# 1. resolución de rutas
class TestResolucionDeRutas(unittest.TestCase):
    def test_common_resuelve_projectroot_dinamicamente(self):
        contenido = _leer("common.ps1")
        self.assertIn("$PSScriptRoot", contenido)
        self.assertIn("ProjectRoot", contenido)

    def test_common_resuelve_python_dinamicamente_no_hardcodeado(self):
        contenido = _leer("common.ps1")
        self.assertIn(".venv", contenido)
        self.assertIn("Get-Command python", contenido)

    def test_ningun_script_hardcodea_la_ruta_del_usuario(self):
        for archivo in SCRIPTS_DIR.glob("*.ps1"):
            with self.subTest(archivo=archivo.name):
                contenido = archivo.read_text(encoding="utf-8")
                self.assertNotIn(r"C:\Users", contenido)
                self.assertNotIn("benic", contenido)


# 2. configuración compartida (no duplicada)
class TestConfiguracionCompartida(unittest.TestCase):
    def test_start_motor_y_start_panel_reutilizan_common(self):
        for nombre in ("start_motor.ps1", "start_panel.ps1", "check_ollama.ps1", "install_tasks.ps1", "status.ps1", "uninstall_tasks.ps1"):
            with self.subTest(nombre=nombre):
                contenido = _leer(nombre)
                self.assertIn('common.ps1', contenido)

    def test_ningun_script_reimplementa_get_projectpython(self):
        # La función se define una sola vez, en common.ps1.
        definiciones = 0
        for archivo in SCRIPTS_DIR.glob("*.ps1"):
            contenido = archivo.read_text(encoding="utf-8")
            definiciones += len(re.findall(r"function\s+Get-ProjectPython", contenido))
        self.assertEqual(definiciones, 1)

    def test_check_ollama_usa_config_redaccion_json_no_duplica_modelo(self):
        contenido = _leer("check_ollama.ps1")
        self.assertIn("config\\redaccion.json", contenido)
        # el nombre del modelo/endpoint no se repite hardcodeado en el .ps1
        self.assertNotIn("qwen3", contenido)


# 6-7-8. scripts Motor/Panel usan la ruta correcta y el working directory correcto
class TestScriptsUsanRutaYWorkingDirectoryCorrectos(unittest.TestCase):
    def test_start_motor_usa_python_y_root_resueltos(self):
        contenido = _leer("start_motor.ps1")
        self.assertIn("Get-ProjectPython", contenido)
        self.assertIn("Get-ProjectRoot", contenido)
        self.assertIn("run_continuo.py", contenido)
        self.assertIn("Set-Location $root", contenido)
        self.assertIn("logs\\motor_continuo.log", contenido)

    def test_start_motor_verifica_ollama_antes_de_arrancar(self):
        contenido = _leer("start_motor.ps1")
        self.assertIn("check_ollama.ps1", contenido)
        # la línea que realmente invoca run_continuo.py no fuerza --redactor
        linea_invocacion = next(l for l in contenido.splitlines() if "run_continuo.py" in l and l.strip().startswith("&"))
        self.assertNotIn("--redactor", linea_invocacion)

    def test_start_panel_usa_python_y_root_resueltos(self):
        contenido = _leer("start_panel.ps1")
        self.assertIn("Get-ProjectPython", contenido)
        self.assertIn("Get-ProjectRoot", contenido)
        self.assertIn("run_panel.py", contenido)
        self.assertIn("Set-Location $root", contenido)

    def test_start_panel_no_fuerza_redactor_mock(self):
        contenido = _leer("start_panel.ps1")
        # la línea que realmente invoca run_panel.py no pasa --redactor:
        # usa config/redaccion.json tal cual, como el resto del proyecto.
        linea_invocacion = next(l for l in contenido.splitlines() if "run_panel.py" in l and l.strip().startswith("&"))
        self.assertNotIn("--redactor", linea_invocacion)

    def test_start_panel_no_verifica_ollama_como_condicion_de_arranque(self):
        # El panel debe poder abrirse igual aunque Ollama esté caído.
        contenido = _leer("start_panel.ps1")
        self.assertNotIn("check_ollama", contenido)

    def test_install_tasks_fija_workingdirectory_explicito(self):
        contenido = _leer("install_tasks.ps1")
        self.assertEqual(contenido.count("-WorkingDirectory $root"), 2)


# 9-10. nombres de tareas y trigger de inicio de sesión
class TestTareasProgramadas(unittest.TestCase):
    def test_nombres_de_tareas_correctos(self):
        contenido = _leer("install_tasks.ps1")
        self.assertIn('"LedesmaParticipa-Motor"', contenido)
        self.assertIn('"LedesmaParticipa-Panel"', contenido)

    def test_trigger_es_atlogon_no_atstartup(self):
        contenido = _leer("install_tasks.ps1")
        self.assertIn("-AtLogOn", contenido)
        self.assertNotIn("-AtStartup", contenido)

    def test_configura_reintentos_ante_fallo_sin_bucle_agresivo(self):
        contenido = _leer("install_tasks.ps1")
        self.assertIn("RestartCount", contenido)
        self.assertIn("RestartInterval", contenido)
        # intervalo en minutos, no segundos: evita restart storms
        self.assertIn("New-TimeSpan -Minutes", contenido)

    def test_evita_segunda_instancia(self):
        contenido = _leer("install_tasks.ps1")
        self.assertIn("MultipleInstances IgnoreNew", contenido)

    def test_no_limite_de_tiempo_de_ejecucion(self):
        contenido = _leer("install_tasks.ps1")
        self.assertIn("ExecutionTimeLimit ([TimeSpan]::Zero)", contenido)


# 11. no contiene contraseña
class TestSinCredenciales(unittest.TestCase):
    def test_ningun_script_contiene_credenciales_embebidas(self):
        # Patrones concretos de una credencial realmente embebida (no
        # palabras sueltas: los scripts explican en comentarios que
        # justamente NO se guarda ninguna contraseña, lo cual es correcto
        # que mencionen).
        patrones_prohibidos = (
            "-password",
            "convertto-securestring",
            "-asplaintext",
            "api_key=",
            "apikey=",
            "token=",
            "secret=",
        )
        for archivo in SCRIPTS_DIR.glob("*.ps1"):
            contenido = archivo.read_text(encoding="utf-8").lower()
            for patron in patrones_prohibidos:
                with self.subTest(archivo=archivo.name, patron=patron):
                    self.assertNotIn(patron, contenido)

    def test_principal_usa_logontype_interactive_sin_password(self):
        contenido = _leer("install_tasks.ps1")
        self.assertIn("-LogonType Interactive", contenido)
        self.assertIn("-RunLevel Limited", contenido)


# 12. panel sigue bind 127.0.0.1
class TestBindLocalhost(unittest.TestCase):
    def test_ningun_script_menciona_0_0_0_0(self):
        for archivo in SCRIPTS_DIR.glob("*.ps1"):
            with self.subTest(archivo=archivo.name):
                self.assertNotIn("0.0.0.0", archivo.read_text(encoding="utf-8"))

    def test_panel_server_sigue_atado_a_127_0_0_1(self):
        from motor_noticias.panel.server import HOST

        self.assertEqual(HOST, "127.0.0.1")

    def test_ningun_script_abre_firewall_ni_reglas_de_red(self):
        patrones = ("New-NetFirewallRule", "netsh advfirewall", "portproxy")
        for archivo in SCRIPTS_DIR.glob("*.ps1"):
            contenido = archivo.read_text(encoding="utf-8")
            for patron in patrones:
                with self.subTest(archivo=archivo.name, patron=patron):
                    self.assertNotIn(patron, contenido)


# 13. uninstall solo elimina tareas del proyecto
class TestUninstallAlcanceAcotado(unittest.TestCase):
    def test_uninstall_solo_referencia_las_dos_tareas_del_proyecto(self):
        contenido = _leer("uninstall_tasks.ps1")
        self.assertIn('"LedesmaParticipa-Motor"', contenido)
        self.assertIn('"LedesmaParticipa-Panel"', contenido)
        # no debe operar sobre un listado sin filtrar (todas las tareas del sistema)
        self.assertNotIn("Get-ScheduledTask |", contenido)
        self.assertNotIn("Get-ScheduledTask -TaskName *", contenido)

    def test_uninstall_no_toca_proyecto_db_ni_logs(self):
        contenido = _leer("uninstall_tasks.ps1")
        for patron in ("Remove-Item", "rm ", "del ", "rd "):
            with self.subTest(patron=patron):
                self.assertNotIn(patron, contenido)


# 14. status es de solo lectura
class TestStatusEsSoloLectura(unittest.TestCase):
    def test_status_no_usa_cmdlets_destructivos_ni_de_escritura(self):
        contenido = _leer("status.ps1")
        prohibidos = (
            "Register-ScheduledTask",
            "Unregister-ScheduledTask",
            "Start-ScheduledTask",
            "Stop-ScheduledTask",
            "Remove-Item",
            "New-Item",
            "Set-Content",
            "Add-Content",
        )
        for patron in prohibidos:
            with self.subTest(patron=patron):
                self.assertNotIn(patron, contenido)

    def test_status_reporta_los_puntos_pedidos(self):
        contenido = _leer("status.ps1")
        for fragmento in (
            "LedesmaParticipa-Motor",
            "LedesmaParticipa-Panel",
            "check_ollama.py",
            "127.0.0.1:8000",
            "Get-ProjectPython",
        ):
            with self.subTest(fragmento=fragmento):
                self.assertIn(fragmento, contenido)


class TestRotacionSimpleDeLogs(unittest.TestCase):
    def test_write_log_implementa_rotacion_simple(self):
        contenido = _leer("common.ps1")
        self.assertIn("Rename-Item", contenido)
        self.assertIn("1MB", contenido)
        self.assertIn("-gt 5", contenido)


if __name__ == "__main__":
    unittest.main()
