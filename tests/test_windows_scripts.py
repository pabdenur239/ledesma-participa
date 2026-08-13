"""Tests offline de los scripts de producción Windows (scripts/windows/).

No se ejecuta PowerShell en ningún momento (no está disponible fuera de
Windows): se valida el CONTENIDO de los .ps1 — rutas resueltas dinámicamente,
configuración compartida (no duplicada), nombres/trigger de las tareas,
ausencia de contraseñas/secretos, bind exclusivo a 127.0.0.1, y que
status.ps1/uninstall_tasks.ps1 sean seguros (solo lectura / alcance acotado).
"""
import re
import shutil
import subprocess
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts" / "windows"

# UTF-8 BOM: Windows PowerShell 5.1 (a diferencia de PowerShell 7+) solo
# detecta un archivo .ps1 como UTF-8 de forma confiable si empieza con este
# BOM; sin él, lee el archivo con la codificación ANSI del sistema y corrompe
# cualquier caracter no ASCII (mojibake), lo que puede llegar a romper el
# parseo si el resultado se parece a una comilla u otro caracter con
# significado sintáctico.
BOM_UTF8 = b"\xef\xbb\xbf"

# Caracteres tipográficos que se evitan a propósito en estos scripts (aunque
# el archivo ya esté bien codificado) para minimizar cualquier fricción con
# parsers/editores más viejos: comillas curvas y guiones Unicode. Los
# caracteres acentuados del español (á, é, í, ó, ú, ñ, ¿, ¡) sí se conservan:
# son parte del idioma del proyecto, no "caracteres tipográficos innecesarios".
CARACTERES_TIPOGRAFICOS_A_EVITAR = (
    "—",  # em dash —
    "–",  # en dash –
    "‘",  # comilla simple izquierda '
    "’",  # comilla simple derecha '
    "“",  # comilla doble izquierda "
    "”",  # comilla doble derecha "
)

PWSH = shutil.which("pwsh")


def _leer(nombre: str) -> str:
    # utf-8-sig: los .ps1 llevan BOM (lo necesita Windows PowerShell 5.1);
    # se lo descarta acá para que las comparaciones de contenido no lo vean.
    return (SCRIPTS_DIR / nombre).read_text(encoding="utf-8-sig")


class TestArchivosExisten(unittest.TestCase):
    def test_scripts_minimos_existen(self):
        for nombre in (
            "common.ps1",
            "check_ollama.ps1",
            "start_motor.ps1",
            "start_panel.ps1",
            "start_informe_diario.ps1",
            "install_tasks.ps1",
            "uninstall_tasks.ps1",
            "status.ps1",
        ):
            with self.subTest(nombre=nombre):
                self.assertTrue((SCRIPTS_DIR / nombre).exists(), f"falta {nombre}")


class TestCodificacionCompatibleConWindowsPowerShell51(unittest.TestCase):
    """Bug real reportado desde Windows: PowerShell 5.1 interpretaba los
    .ps1 (UTF-8 sin BOM) con la codificación ANSI del sistema, produciendo
    mojibake ("finalizÃ³") y en algún punto un error de parseo (comilla sin
    terminar). La causa confirmada es la falta de BOM; la corrección es
    guardarlos como UTF-8 con BOM y evitar además guiones/comillas Unicode
    en los mensajes, aunque no sean la causa raíz."""

    def test_todos_los_ps1_tienen_bom_utf8(self):
        archivos = list(SCRIPTS_DIR.glob("*.ps1"))
        self.assertTrue(archivos, "no se encontraron archivos .ps1 para verificar")
        for archivo in archivos:
            with self.subTest(archivo=archivo.name):
                inicio = archivo.read_bytes()[:3]
                self.assertEqual(
                    inicio, BOM_UTF8, f"{archivo.name} no empieza con BOM UTF-8 (PowerShell 5.1 lo necesita)"
                )

    def test_ningun_ps1_tiene_guiones_o_comillas_unicode(self):
        for archivo in SCRIPTS_DIR.glob("*.ps1"):
            contenido = archivo.read_text(encoding="utf-8-sig")
            for caracter in CARACTERES_TIPOGRAFICOS_A_EVITAR:
                with self.subTest(archivo=archivo.name, caracter=repr(caracter)):
                    self.assertNotIn(caracter, contenido)

    def test_los_acentos_del_espanol_se_conservan(self):
        # La corrección es de codificación, no de idioma: los acentos
        # siguen presentes (y ahora se van a leer bien en PowerShell 5.1).
        contenido = _leer("common.ps1")
        self.assertTrue(any(c in contenido for c in "áéíóúñ"))

    @unittest.skipUnless(PWSH, "pwsh no disponible en este entorno: se omite la validación con el parser real")
    def test_todos_los_ps1_parsean_sin_errores_con_powershell_real(self):
        for archivo in SCRIPTS_DIR.glob("*.ps1"):
            with self.subTest(archivo=archivo.name):
                comando = (
                    "$errores = $null; $tokens = $null; "
                    f"[System.Management.Automation.Language.Parser]::ParseFile('{archivo}', [ref]$tokens, [ref]$errores) "
                    "| Out-Null; "
                    "if ($errores.Count -gt 0) { $errores | ForEach-Object { Write-Error $_.Message }; exit 1 } "
                    "else { exit 0 }"
                )
                resultado = subprocess.run(
                    [PWSH, "-NoProfile", "-NonInteractive", "-Command", comando],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                self.assertEqual(
                    resultado.returncode, 0, f"{archivo.name} tiene errores de parseo:\n{resultado.stderr}"
                )

    @unittest.skipUnless(PWSH, "pwsh no disponible en este entorno: se omite la validación funcional real")
    def test_common_ps1_se_puede_dot_sourcear_y_escribir_log(self):
        # Prueba funcional real (no solo sintáctica): dot-source de
        # common.ps1 y una escritura de log con acentos, con el propio
        # intérprete de PowerShell.
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            comando = (
                f". '{SCRIPTS_DIR / 'common.ps1'}'; "
                "Write-Log -LogFile 'prueba.log' -Mensaje 'codigo finalizo rotacion con acentos: áéíóú'; "
                f"Get-Content (Join-Path (Get-ProjectRoot) 'logs/prueba.log')"
            )
            resultado = subprocess.run(
                [PWSH, "-NoProfile", "-NonInteractive", "-Command", comando],
                capture_output=True,
                text=True,
                timeout=30,
                cwd=str(SCRIPTS_DIR.parent.parent),
            )
            self.assertEqual(resultado.returncode, 0, resultado.stderr)
            self.assertIn("áéíóú", resultado.stdout)
            # limpieza: no versionar el log real generado por la prueba
            logs_dir = SCRIPTS_DIR.parent.parent / "logs"
            if logs_dir.exists():
                shutil.rmtree(logs_dir)


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
                contenido = archivo.read_text(encoding="utf-8-sig")
                self.assertNotIn(r"C:\Users", contenido)
                self.assertNotIn("benic", contenido)


# 2. configuración compartida (no duplicada)
class TestConfiguracionCompartida(unittest.TestCase):
    def test_start_motor_y_start_panel_reutilizan_common(self):
        for nombre in (
            "start_motor.ps1",
            "start_panel.ps1",
            "start_informe_diario.ps1",
            "check_ollama.ps1",
            "install_tasks.ps1",
            "status.ps1",
            "uninstall_tasks.ps1",
        ):
            with self.subTest(nombre=nombre):
                contenido = _leer(nombre)
                self.assertIn('common.ps1', contenido)

    def test_ningun_script_reimplementa_get_projectpython(self):
        # La función se define una sola vez, en common.ps1.
        definiciones = 0
        for archivo in SCRIPTS_DIR.glob("*.ps1"):
            contenido = archivo.read_text(encoding="utf-8-sig")
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
        self.assertEqual(contenido.count("-WorkingDirectory $root"), 3)


# 9-10. nombres de tareas y trigger de inicio de sesión
class TestTareasProgramadas(unittest.TestCase):
    def test_nombres_de_tareas_correctos(self):
        contenido = _leer("install_tasks.ps1")
        self.assertIn('"LedesmaParticipa-Motor"', contenido)
        self.assertIn('"LedesmaParticipa-Panel"', contenido)
        self.assertIn('"LedesmaParticipa-InformeDiario"', contenido)

    def test_trigger_motor_y_panel_es_atlogon_no_atstartup(self):
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


# 11. configuración de la tarea Windows del informe diario
class TestTareaInformeDiario(unittest.TestCase):
    def test_script_wrapper_existe_y_no_depende_de_ollama(self):
        self.assertTrue((SCRIPTS_DIR / "start_informe_diario.ps1").exists())
        contenido = _leer("start_informe_diario.ps1")
        self.assertIn("generar_informe_diario.py", contenido)
        # no hay ninguna invocación real a check_ollama (más allá de que un
        # comentario explique por qué no hace falta)
        lineas_invocacion = [l for l in contenido.splitlines() if l.strip().startswith("&")]
        self.assertTrue(lineas_invocacion)
        for linea in lineas_invocacion:
            self.assertNotIn("check_ollama", linea)

    def test_trigger_diario_a_las_0730(self):
        contenido = _leer("install_tasks.ps1")
        self.assertIn("-Daily", contenido)
        self.assertIn("07:30", contenido)

    def test_start_when_available_habilitado(self):
        # Se ejecuta al volver a estar disponible si la notebook estaba
        # apagada a las 07:30 — mismo $settings compartido por las 3 tareas.
        contenido = _leer("install_tasks.ps1")
        self.assertIn("-StartWhenAvailable", contenido)

    def test_informe_diario_usa_la_misma_politica_de_reintentos_e_instancia_unica(self):
        contenido = _leer("install_tasks.ps1")
        self.assertIn("$accionInforme", contenido)
        # se registra con el mismo objeto $settings (RestartCount/
        # RestartInterval/IgnoreNew/ExecutionTimeLimit) que Motor y Panel:
        # no hay un segundo bloque de $settings solo para esta tarea.
        self.assertEqual(contenido.count("New-ScheduledTaskSettingsSet"), 1)
        self.assertIn('Register-ScheduledTask -TaskName $TareaInforme', contenido)

    def test_informe_diario_registrado_con_action_y_trigger_propios(self):
        contenido = _leer("install_tasks.ps1")
        self.assertIn("$triggerInforme", contenido)
        self.assertIn("start_informe_diario.ps1", contenido)


# 12. preservación de Motor y Panel al agregar la tercera tarea
class TestPreservacionMotorYPanel(unittest.TestCase):
    def test_motor_y_panel_conservan_su_trigger_y_retraso(self):
        contenido = _leer("install_tasks.ps1")
        self.assertIn('$DelayMotor = "PT30S"', contenido)
        self.assertIn('$DelayPanel = "PT45S"', contenido)
        self.assertIn("$triggerMotor = New-ScheduledTaskTrigger -AtLogOn", contenido)
        self.assertIn("$triggerPanel = New-ScheduledTaskTrigger -AtLogOn", contenido)

    def test_motor_y_panel_siguen_registrados(self):
        contenido = _leer("install_tasks.ps1")
        self.assertIn('Register-ScheduledTask -TaskName $TareaMotor', contenido)
        self.assertIn('Register-ScheduledTask -TaskName $TareaPanel', contenido)

    def test_start_motor_y_start_panel_sin_cambios_de_fondo(self):
        # Siguen verificando (Motor) u omitiendo (Panel) Ollama exactamente
        # igual que antes de agregar la tercera tarea.
        self.assertIn("check_ollama.ps1", _leer("start_motor.ps1"))
        self.assertNotIn("check_ollama", _leer("start_panel.ps1"))

    def test_uninstall_incluye_las_tres_tareas(self):
        contenido = _leer("uninstall_tasks.ps1")
        self.assertIn('"LedesmaParticipa-Motor"', contenido)
        self.assertIn('"LedesmaParticipa-Panel"', contenido)
        self.assertIn('"LedesmaParticipa-InformeDiario"', contenido)

    def test_status_reporta_las_tres_tareas(self):
        contenido = _leer("status.ps1")
        self.assertIn('"LedesmaParticipa-Motor"', contenido)
        self.assertIn('"LedesmaParticipa-Panel"', contenido)
        self.assertIn('"LedesmaParticipa-InformeDiario"', contenido)


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
            contenido = archivo.read_text(encoding="utf-8-sig").lower()
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
                self.assertNotIn("0.0.0.0", archivo.read_text(encoding="utf-8-sig"))

    def test_panel_server_sigue_atado_a_127_0_0_1(self):
        from motor_noticias.panel.server import HOST

        self.assertEqual(HOST, "127.0.0.1")

    def test_ningun_script_abre_firewall_ni_reglas_de_red(self):
        patrones = ("New-NetFirewallRule", "netsh advfirewall", "portproxy")
        for archivo in SCRIPTS_DIR.glob("*.ps1"):
            contenido = archivo.read_text(encoding="utf-8-sig")
            for patron in patrones:
                with self.subTest(archivo=archivo.name, patron=patron):
                    self.assertNotIn(patron, contenido)


# 13. uninstall solo elimina tareas del proyecto
class TestUninstallAlcanceAcotado(unittest.TestCase):
    def test_uninstall_solo_referencia_las_tareas_del_proyecto(self):
        contenido = _leer("uninstall_tasks.ps1")
        self.assertIn('"LedesmaParticipa-Motor"', contenido)
        self.assertIn('"LedesmaParticipa-Panel"', contenido)
        self.assertIn('"LedesmaParticipa-InformeDiario"', contenido)
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


class TestWriteLogToleraConcurrencia(unittest.TestCase):
    """Bug real: Motor y Panel arrancando casi al mismo tiempo escribían a
    la vez logs\\startup.log y Add-Content fallaba con "el proceso no puede
    obtener acceso al archivo...". Write-Log ahora serializa la escritura
    entre procesos con un Mutex con nombre (solo .NET estándar) y reintenta
    ante un bloqueo puntual, sin ocultar otros errores."""

    def test_write_log_usa_mutex_con_nombre_para_serializar_entre_procesos(self):
        contenido = _leer("common.ps1")
        self.assertIn("System.Threading.Mutex", contenido)
        self.assertIn("WaitOne", contenido)
        self.assertIn("ReleaseMutex", contenido)

    def test_write_log_reintenta_solo_ante_ioexception_no_oculta_otros_errores(self):
        contenido = _leer("common.ps1")
        self.assertIn("catch [System.IO.IOException]", contenido)
        # tras agotar los reintentos, el error se relanza (throw), no se
        # traga silenciosamente
        cuerpo_catch = contenido.split("catch [System.IO.IOException]", 1)[1]
        self.assertIn("throw", cuerpo_catch[: cuerpo_catch.index("Start-Sleep")])

    def test_write_log_maneja_mutex_abandonado(self):
        # Si el proceso dueño anterior del mutex terminó sin liberarlo
        # (cierre inesperado), igual se debe poder seguir escribiendo.
        contenido = _leer("common.ps1")
        self.assertIn("AbandonedMutexException", contenido)

    @unittest.skipUnless(PWSH, "pwsh no disponible en este entorno: se omite la prueba real de concurrencia")
    def test_escrituras_concurrentes_no_pierden_lineas(self):
        # Prueba funcional real (no solo estática): varios procesos de
        # PowerShell escribiendo al mismo logs\startup.log en simultáneo,
        # sin ninguna línea perdida.
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "scripts" / "windows").mkdir(parents=True)
            shutil.copy(SCRIPTS_DIR / "common.ps1", tmp_path / "scripts" / "windows" / "common.ps1")

            num_jobs = 8
            lineas_por_job = 5
            comando = f"""
            $jobs = @()
            for ($i = 0; $i -lt {num_jobs}; $i++) {{
                $jobs += Start-Job -ScriptBlock {{
                    param($root, $idx, $n)
                    . (Join-Path $root 'scripts/windows/common.ps1')
                    for ($j = 0; $j -lt $n; $j++) {{
                        Write-Log -LogFile 'startup.log' -Mensaje "P$idx-L$j"
                    }}
                }} -ArgumentList '{tmp_path}', $i, {lineas_por_job}
            }}
            Wait-Job -Job $jobs | Out-Null
            $fallidos = ($jobs | Where-Object {{ $_.State -eq 'Failed' }}).Count
            Remove-Job -Job $jobs
            Write-Output "FALLIDOS:$fallidos"
            """
            resultado = subprocess.run(
                [PWSH, "-NoProfile", "-NonInteractive", "-Command", comando],
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(resultado.returncode, 0, resultado.stderr)
            self.assertIn("FALLIDOS:0", resultado.stdout)

            log_path = tmp_path / "logs" / "startup.log"
            self.assertTrue(log_path.exists())
            lineas = log_path.read_text(encoding="utf-8").splitlines()

            esperadas = {f"P{i}-L{j}" for i in range(num_jobs) for j in range(lineas_por_job)}
            encontradas = {marca for marca in esperadas if any(marca in linea for linea in lineas)}
            faltantes = esperadas - encontradas
            self.assertEqual(faltantes, set(), f"líneas perdidas bajo escritura concurrente: {faltantes}")


if __name__ == "__main__":
    unittest.main()
