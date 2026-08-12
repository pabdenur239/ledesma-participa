# check_ollama.ps1 — verifica que Ollama esté disponible y que el modelo
# configurado (config/redaccion.json) esté instalado, con reintentos
# acotados por si Ollama todavía está arrancando. NO instala ni descarga
# nada. NO reemplaza Ollama por otro motor si falla: solo lo registra.
#
# Exit code: 0 = OK; 1 = API no responde; 2 = responde pero falta el modelo.

param(
    [int]$EsperaMaximaSegundos = 60,
    [int]$IntervaloSegundos = 5
)

. (Join-Path $PSScriptRoot "common.ps1")

$LogFile = "ollama_check.log"
$root = Get-ProjectRoot
$python = Get-ProjectPython
$scriptPy = Join-Path $PSScriptRoot "check_ollama.py"
$configPath = Join-Path $root "config\redaccion.json"

Write-Log -LogFile $LogFile -Mensaje "Verificando Ollama (espera máxima ${EsperaMaximaSegundos}s, intervalo ${IntervaloSegundos}s)..."

$salida = & $python $scriptPy --config $configPath --espera-maxima $EsperaMaximaSegundos --intervalo $IntervaloSegundos 2>&1
$codigo = $LASTEXITCODE

foreach ($linea in $salida) {
    Write-Log -LogFile $LogFile -Mensaje $linea
}

if ($codigo -eq 0) {
    Write-Log -LogFile $LogFile -Mensaje "Ollama disponible y modelo presente."
} else {
    Write-Log -LogFile $LogFile -Mensaje "Ollama NO disponible o modelo faltante (código $codigo)." -Nivel "ERROR"
}

exit $codigo
