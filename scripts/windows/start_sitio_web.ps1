# start_sitio_web.ps1 - regenera el sitio web publico (docs/) a partir de
# las noticias ya publicadas en la base. Proceso de solo lectura sobre la
# base de datos: no publica nada nuevo en Facebook/Instagram ni depende de
# Ollama, solo refleja en la web lo que el motor ya publico.

. (Join-Path $PSScriptRoot "common.ps1")

$LogFile = "startup.log"
$root = Get-ProjectRoot

Write-Log -LogFile $LogFile -Mensaje "start_sitio_web.ps1: iniciando."

if (-not (Test-Path (Join-Path $root "generar_sitio_web.py"))) {
    Write-Log -LogFile $LogFile -Mensaje "start_sitio_web.ps1: no se encontro generar_sitio_web.py en $root." -Nivel "ERROR"
    exit 1
}

$python = Get-ProjectPython
Set-Location $root

Write-Log -LogFile $LogFile -Mensaje "start_sitio_web.ps1: regenerando el sitio ($python) en $root."

& $python (Join-Path $root "generar_sitio_web.py") 2>&1 | ForEach-Object {
    Write-Log -LogFile "sitio_web.log" -Mensaje $_
}
$exitCode = $LASTEXITCODE

Write-Log -LogFile $LogFile -Mensaje "start_sitio_web.ps1: finalizo con codigo $exitCode."
exit $exitCode
