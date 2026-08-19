# start_meta_programacion.ps1 - genera la programacion diaria de publicacion
# en Meta (franjas fijas: 07:30 informe diario + 14 franjas por cascada
# territorial). No depende de Ollama. Corre una vez y termina.

. (Join-Path $PSScriptRoot "common.ps1")

$LogFile = "startup.log"
$root = Get-ProjectRoot

Write-Log -LogFile $LogFile -Mensaje "start_meta_programacion.ps1: iniciando."

if (-not (Test-Path (Join-Path $root "generar_programacion_meta.py"))) {
    Write-Log -LogFile $LogFile -Mensaje "start_meta_programacion.ps1: no se encontro generar_programacion_meta.py en $root." -Nivel "ERROR"
    exit 1
}

$python = Get-ProjectPython
Set-Location $root

Write-Log -LogFile $LogFile -Mensaje "start_meta_programacion.ps1: generando programacion ($python) en $root."

& $python (Join-Path $root "generar_programacion_meta.py") 2>&1 | ForEach-Object {
    Write-Log -LogFile "meta_programacion.log" -Mensaje $_
}
$exitCode = $LASTEXITCODE

Write-Log -LogFile $LogFile -Mensaje "start_meta_programacion.ps1: finalizo con codigo $exitCode."
exit $exitCode
