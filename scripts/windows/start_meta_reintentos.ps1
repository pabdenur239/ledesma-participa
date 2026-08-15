# start_meta_reintentos.ps1 - reintenta (de forma acotada) publicaciones de
# Meta que quedaron en estado de error, red social por red social (nunca
# vuelve a publicar en una red que ya tuvo exito). No depende de Ollama.

. (Join-Path $PSScriptRoot "common.ps1")

$LogFile = "startup.log"
$root = Get-ProjectRoot

Write-Log -LogFile $LogFile -Mensaje "start_meta_reintentos.ps1: iniciando."

if (-not (Test-Path (Join-Path $root "reintentar_publicaciones_meta.py"))) {
    Write-Log -LogFile $LogFile -Mensaje "start_meta_reintentos.ps1: no se encontro reintentar_publicaciones_meta.py en $root." -Nivel "ERROR"
    exit 1
}

$python = Get-ProjectPython
Set-Location $root

Write-Log -LogFile $LogFile -Mensaje "start_meta_reintentos.ps1: reintentando pendientes ($python) en $root."

& $python (Join-Path $root "reintentar_publicaciones_meta.py") 2>&1 | ForEach-Object {
    Write-Log -LogFile "meta_reintentos.log" -Mensaje $_
}
$exitCode = $LASTEXITCODE

Write-Log -LogFile $LogFile -Mensaje "start_meta_reintentos.ps1: finalizo con codigo $exitCode."
exit $exitCode
