# start_panel.ps1 — inicia el Panel (run_panel.py) con el intérprete Python
# real del proyecto y el WorkingDirectory correcto. A propósito NO verifica
# Ollama antes de arrancar: el Panel debe poder abrirse igual aunque Ollama
# esté caído (solo hace falta al cargar una noticia nueva vía redactor real,
# no para revisar/aprobar/rechazar lo ya preparado). Usa
# config/redaccion.json tal cual (sin pasar --redactor mock): el panel
# queda con el mismo redactor configurado que el resto del proyecto.
#
# Bind exclusivo a 127.0.0.1 ya está fijo en motor_noticias/panel/server.py
# (HOST, no configurable): este script no lo cambia ni lo puede cambiar.

. (Join-Path $PSScriptRoot "common.ps1")

$LogFile = "startup.log"
$root = Get-ProjectRoot

Write-Log -LogFile $LogFile -Mensaje "start_panel.ps1: iniciando."

if (-not (Test-Path (Join-Path $root "run_panel.py"))) {
    Write-Log -LogFile $LogFile -Mensaje "start_panel.ps1: no se encontró run_panel.py en $root." -Nivel "ERROR"
    exit 1
}

$python = Get-ProjectPython
Set-Location $root

Write-Log -LogFile $LogFile -Mensaje "start_panel.ps1: iniciando Panel ($python) en $root — http://127.0.0.1:8000"

# run_panel.py no tiene logging propio con fecha/hora (solo imprime al
# arrancar): se timestampea cada línea de su salida vía Write-Log hacia
# logs\panel.log, reutilizando la misma rotación simple que el resto.
& $python (Join-Path $root "run_panel.py") 2>&1 | ForEach-Object {
    Write-Log -LogFile "panel.log" -Mensaje $_
}
$exitCode = $LASTEXITCODE

Write-Log -LogFile $LogFile -Mensaje "start_panel.ps1: Panel finalizó con código $exitCode."
exit $exitCode
