# status.ps1 - diagnóstico de solo lectura. No registra, desregistra, ni
# inicia/detiene nada. Seguro para correr en cualquier momento.

. (Join-Path $PSScriptRoot "common.ps1")

Write-Host "=== Estado Ledesma Participa (Windows) ==="
Write-Host ""

$root = Get-ProjectRoot
Write-Host "Proyecto: $root"
if (Test-Path (Join-Path $root "run_continuo.py")) {
    Write-Host "  -> encontrado OK"
} else {
    Write-Host "  -> NO encontrado (revisar la ubicación real del repo)"
}

try {
    $python = Get-ProjectPython
    Write-Host "Python: $python"
} catch {
    Write-Host "Python: NO encontrado (ni .venv ni en PATH)"
    $python = $null
}

Write-Host ""
Write-Host "--- Tareas programadas ---"
foreach ($tarea in @("LedesmaParticipa-Motor", "LedesmaParticipa-Panel", "LedesmaParticipa-InformeDiario")) {
    $t = Get-ScheduledTask -TaskName $tarea -ErrorAction SilentlyContinue
    if ($t) {
        $info = Get-ScheduledTaskInfo -TaskName $tarea
        Write-Host "$tarea : existe. Estado: $($t.State). Última ejecución: $($info.LastRunTime). Último resultado: $($info.LastTaskResult)"
    } else {
        Write-Host "$tarea : NO existe (correr install_tasks.ps1)"
    }
}

Write-Host ""
Write-Host "--- Ollama ---"
if ($python) {
    $configPath = Join-Path $root "config\redaccion.json"
    $salida = & $python (Join-Path $PSScriptRoot "check_ollama.py") --config $configPath --espera-maxima 5 --intervalo 5
    foreach ($linea in $salida) { Write-Host $linea }
} else {
    Write-Host "No se pudo verificar (no hay Python resuelto)."
}

Write-Host ""
Write-Host "--- Panel (http://127.0.0.1:8000) ---"
try {
    $resp = Invoke-WebRequest -Uri "http://127.0.0.1:8000/" -UseBasicParsing -TimeoutSec 3
    Write-Host "Responde: HTTP $($resp.StatusCode)"
} catch {
    Write-Host "No responde."
}

Write-Host ""
Write-Host "Logs en: $(Join-Path $root 'logs')"
