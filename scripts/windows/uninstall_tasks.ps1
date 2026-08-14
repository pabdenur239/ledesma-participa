# uninstall_tasks.ps1 - elimina EXCLUSIVAMENTE las tareas programadas de
# Ledesma Participa. No toca el proyecto, la base de datos, los logs,
# Ollama, los modelos ni Python.

. (Join-Path $PSScriptRoot "common.ps1")

$Tareas = @(
    "LedesmaParticipa-Motor",
    "LedesmaParticipa-Panel",
    "LedesmaParticipa-InformeDiario",
    "LedesmaParticipa-MetaProgramacion",
    "LedesmaParticipa-MetaPlacas",
    "LedesmaParticipa-MetaPublicar",
    "LedesmaParticipa-MetaReintentos"
)

foreach ($tarea in $Tareas) {
    $existente = Get-ScheduledTask -TaskName $tarea -ErrorAction SilentlyContinue
    if ($existente) {
        Unregister-ScheduledTask -TaskName $tarea -Confirm:$false
        Write-Log -LogFile "startup.log" -Mensaje "uninstall_tasks.ps1: tarea '$tarea' eliminada."
        Write-Host "Eliminada: $tarea"
    } else {
        Write-Host "No existía: $tarea"
    }
}

Write-Host ""
Write-Host "El proyecto, la base de datos, los logs, Ollama y los modelos no fueron tocados."
