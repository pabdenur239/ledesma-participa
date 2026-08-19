# start_meta_urgentes.ps1 - publica de inmediato en Facebook e Instagram las
# propuestas urgentes (ultimo momento local/departamental confirmado) del
# dia, sin esperar la siguiente franja fija. No depende de Ollama.

. (Join-Path $PSScriptRoot "common.ps1")

$LogFile = "startup.log"
$root = Get-ProjectRoot

Write-Log -LogFile $LogFile -Mensaje "start_meta_urgentes.ps1: iniciando."

if (-not (Test-Path (Join-Path $root "publicar_urgentes_meta.py"))) {
    Write-Log -LogFile $LogFile -Mensaje "start_meta_urgentes.ps1: no se encontro publicar_urgentes_meta.py en $root." -Nivel "ERROR"
    exit 1
}

$python = Get-ProjectPython
Set-Location $root

Write-Log -LogFile $LogFile -Mensaje "start_meta_urgentes.ps1: publicando urgentes ($python) en $root."

& $python (Join-Path $root "publicar_urgentes_meta.py") 2>&1 | ForEach-Object {
    Write-Log -LogFile "meta_urgentes.log" -Mensaje $_
}
$exitCode = $LASTEXITCODE

Write-Log -LogFile $LogFile -Mensaje "start_meta_urgentes.ps1: finalizo con codigo $exitCode."
exit $exitCode
