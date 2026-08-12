# start_motor.ps1 - inicia el Motor Continuo (run_continuo.py) con el
# intérprete Python real del proyecto y el WorkingDirectory correcto, sin
# depender del directorio actual del Programador de tareas.
#
# Antes de arrancar verifica Ollama (nunca sustituye por Mock si falla:
# aborta y deja el error registrado) y que el proyecto exista. La segunda
# instancia la evita el propio lock de run_continuo.py (data/run_continuo.lock,
# reutilizado tal cual, sin agregar otro mecanismo) más la política
# "IgnoreNew" configurada en install_tasks.ps1.

. (Join-Path $PSScriptRoot "common.ps1")

$LogFile = "startup.log"
$root = Get-ProjectRoot

Write-Log -LogFile $LogFile -Mensaje "start_motor.ps1: iniciando."

if (-not (Test-Path (Join-Path $root "run_continuo.py"))) {
    Write-Log -LogFile $LogFile -Mensaje "start_motor.ps1: no se encontró run_continuo.py en $root." -Nivel "ERROR"
    exit 1
}

& (Join-Path $PSScriptRoot "check_ollama.ps1") | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Log -LogFile $LogFile -Mensaje "start_motor.ps1: Ollama no disponible (código $LASTEXITCODE). No se inicia el Motor Continuo; no se reemplaza por RedactorMock. Ver logs\ollama_check.log." -Nivel "ERROR"
    exit 1
}

$python = Get-ProjectPython
Set-Location $root

Write-Log -LogFile $LogFile -Mensaje "start_motor.ps1: iniciando Motor Continuo ($python) en $root."

# run_continuo.py ya tiene su propio logging con fecha/hora y niveles
# (INFO/ERROR): se lo redirige a logs\motor_continuo.log en vez de
# data\logs\run_continuo.log, para mantener todos los logs de producción
# juntos, sin reimplementar ese logging.
& $python (Join-Path $root "run_continuo.py") --log (Join-Path $root "logs\motor_continuo.log")
$exitCode = $LASTEXITCODE

Write-Log -LogFile $LogFile -Mensaje "start_motor.ps1: Motor Continuo finalizó con código $exitCode."
exit $exitCode
