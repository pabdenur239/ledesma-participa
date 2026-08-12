# install_tasks.ps1 — registra las tareas programadas de Ledesma Participa
# para el usuario actual (sesión interactiva, sin guardar ninguna
# contraseña). Reproducible: se puede correr de nuevo (usa -Force) sin
# duplicar tareas.
#
# Trigger: al iniciar sesión el usuario actual (AtLogOn) — no AtStartup, para
# no complicar el arranque de Ollama ni depender de que el perfil de usuario
# ya esté cargado.
#
# Si esto falla por permisos, correr esta consola de PowerShell "Como
# administrador" solo para este paso puntual (ver README).

. (Join-Path $PSScriptRoot "common.ps1")

$root = Get-ProjectRoot
$null = Get-ProjectPython  # valida que exista un intérprete antes de instalar nada

$TareaMotor = "LedesmaParticipa-Motor"
$TareaPanel = "LedesmaParticipa-Panel"

# Retraso tras el inicio de sesión: le da tiempo a Windows/Ollama a terminar
# de arrancar antes de que el Motor intente su primer ciclo.
$DelayMotor = "PT30S"   # 30 segundos
$DelayPanel = "PT45S"   # levemente posterior al Motor

# Reintentos ante fallo: 3 intentos, cada 2 minutos — evita "restart storms"
# sin dejar de recuperarse ante un fallo puntual.
$RestartCount = 3
$RestartInterval = (New-TimeSpan -Minutes 2)

$triggerMotor = New-ScheduledTaskTrigger -AtLogOn
$triggerMotor.Delay = $DelayMotor

$triggerPanel = New-ScheduledTaskTrigger -AtLogOn
$triggerPanel.Delay = $DelayPanel

$accionMotor = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$(Join-Path $PSScriptRoot 'start_motor.ps1')`"" `
    -WorkingDirectory $root

$accionPanel = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$(Join-Path $PSScriptRoot 'start_panel.ps1')`"" `
    -WorkingDirectory $root

# MultipleInstances IgnoreNew: si la tarea ya está corriendo, Task Scheduler
# no arranca una segunda instancia (además del lock propio del Motor).
# ExecutionTimeLimit cero: no hay límite de tiempo de ejecución (ambos
# procesos corren indefinidamente por diseño).
$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -RestartCount $RestartCount `
    -RestartInterval $RestartInterval `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -StartWhenAvailable `
    -DontStopOnIdleEnd

# LogonType Interactive + RunLevel Limited: corre bajo la sesión del usuario
# actual, sin privilegios elevados y sin necesidad de guardar contraseña.
$principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive `
    -RunLevel Limited

Register-ScheduledTask -TaskName $TareaMotor -Trigger $triggerMotor -Action $accionMotor -Settings $settings -Principal $principal -Force | Out-Null
Register-ScheduledTask -TaskName $TareaPanel -Trigger $triggerPanel -Action $accionPanel -Settings $settings -Principal $principal -Force | Out-Null

Write-Log -LogFile "startup.log" -Mensaje "install_tasks.ps1: tareas '$TareaMotor' y '$TareaPanel' registradas (retraso ${DelayMotor}/${DelayPanel}, reintentos $RestartCount cada $($RestartInterval.TotalMinutes) min)."

Write-Host "Tareas registradas:"
Write-Host "  - $TareaMotor (retraso $DelayMotor tras inicio de sesión)"
Write-Host "  - $TareaPanel (retraso $DelayPanel tras inicio de sesión)"
Write-Host ""
Write-Host "Verificá con: scripts\windows\status.ps1"
Write-Host "Para iniciarlas ahora sin esperar el próximo inicio de sesión:"
Write-Host "  Start-ScheduledTask -TaskName '$TareaMotor'"
Write-Host "  Start-ScheduledTask -TaskName '$TareaPanel'"
