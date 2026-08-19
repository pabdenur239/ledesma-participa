# start_meta_publicar.ps1 - publica en Facebook e Instagram el contenido
# programado para la franja horaria actual (publicar_meta.py detecta sola
# la franja mas cercana a la hora actual). Se dispara una vez por cada una
# de las 15 franjas fijas del dia (ver install_tasks.ps1). No depende de
# Ollama.

. (Join-Path $PSScriptRoot "common.ps1")

$LogFile = "startup.log"
$root = Get-ProjectRoot

Write-Log -LogFile $LogFile -Mensaje "start_meta_publicar.ps1: iniciando."

if (-not (Test-Path (Join-Path $root "publicar_meta.py"))) {
    Write-Log -LogFile $LogFile -Mensaje "start_meta_publicar.ps1: no se encontro publicar_meta.py en $root." -Nivel "ERROR"
    exit 1
}

$python = Get-ProjectPython
Set-Location $root

Write-Log -LogFile $LogFile -Mensaje "start_meta_publicar.ps1: publicando franja actual ($python) en $root."

& $python (Join-Path $root "publicar_meta.py") 2>&1 | ForEach-Object {
    Write-Log -LogFile "meta_publicar.log" -Mensaje $_
}
$exitCode = $LASTEXITCODE

Write-Log -LogFile $LogFile -Mensaje "start_meta_publicar.ps1: finalizo con codigo $exitCode."
exit $exitCode
