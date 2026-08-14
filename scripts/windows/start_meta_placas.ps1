# start_meta_placas.ps1 - genera por adelantado las placas del dia para
# Meta (y aprueba automaticamente el contenido apto, ver
# motor_noticias/meta/programacion.py). No depende de Ollama. Corre una vez
# y termina; se dispara despues de start_meta_programacion.ps1.

. (Join-Path $PSScriptRoot "common.ps1")

$LogFile = "startup.log"
$root = Get-ProjectRoot

Write-Log -LogFile $LogFile -Mensaje "start_meta_placas.ps1: iniciando."

if (-not (Test-Path (Join-Path $root "generar_placas_meta.py"))) {
    Write-Log -LogFile $LogFile -Mensaje "start_meta_placas.ps1: no se encontro generar_placas_meta.py en $root." -Nivel "ERROR"
    exit 1
}

$python = Get-ProjectPython
Set-Location $root

Write-Log -LogFile $LogFile -Mensaje "start_meta_placas.ps1: generando placas ($python) en $root."

& $python (Join-Path $root "generar_placas_meta.py") 2>&1 | ForEach-Object {
    Write-Log -LogFile "meta_placas.log" -Mensaje $_
}
$exitCode = $LASTEXITCODE

Write-Log -LogFile $LogFile -Mensaje "start_meta_placas.ps1: finalizo con codigo $exitCode."
exit $exitCode
