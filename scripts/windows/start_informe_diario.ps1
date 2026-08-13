# start_informe_diario.ps1 - genera el informe diario de clima y dólar
# (generar_informe_diario.py) con el intérprete Python real del proyecto y
# el WorkingDirectory correcto. No depende de Ollama (el texto se arma de
# forma determinística, sin modelo de lenguaje), así que no verifica
# check_ollama.ps1 antes de arrancar. Corre una vez y termina (no es un
# proceso de larga duración como Motor/Panel); el disparo diario a las
# 07:30 lo hace la tarea programada, no este script.

. (Join-Path $PSScriptRoot "common.ps1")

$LogFile = "startup.log"
$root = Get-ProjectRoot

Write-Log -LogFile $LogFile -Mensaje "start_informe_diario.ps1: iniciando."

if (-not (Test-Path (Join-Path $root "generar_informe_diario.py"))) {
    Write-Log -LogFile $LogFile -Mensaje "start_informe_diario.ps1: no se encontró generar_informe_diario.py en $root." -Nivel "ERROR"
    exit 1
}

$python = Get-ProjectPython
Set-Location $root

Write-Log -LogFile $LogFile -Mensaje "start_informe_diario.ps1: generando informe diario ($python) en $root."

# generar_informe_diario.py no tiene logging propio con fecha/hora (solo
# imprime): se timestampea cada línea de su salida vía Write-Log hacia
# logs\informe_diario.log, igual que start_panel.ps1 con panel.log.
& $python (Join-Path $root "generar_informe_diario.py") 2>&1 | ForEach-Object {
    Write-Log -LogFile "informe_diario.log" -Mensaje $_
}
$exitCode = $LASTEXITCODE

Write-Log -LogFile $LogFile -Mensaje "start_informe_diario.ps1: finalizó con código $exitCode."
exit $exitCode
