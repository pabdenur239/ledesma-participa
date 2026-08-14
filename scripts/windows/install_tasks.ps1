# install_tasks.ps1 - registra las tareas programadas de Ledesma Participa
# para el usuario actual (sesión interactiva, sin guardar ninguna
# contraseña). Reproducible: se puede correr de nuevo (usa -Force) sin
# duplicar tareas.
#
# Trigger: al iniciar sesión el usuario actual (AtLogOn) - no AtStartup, para
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
$TareaInforme = "LedesmaParticipa-InformeDiario"
$TareaMetaProgramacion = "LedesmaParticipa-MetaProgramacion"
$TareaMetaPlacas = "LedesmaParticipa-MetaPlacas"
$TareaMetaPublicar = "LedesmaParticipa-MetaPublicar"
$TareaMetaReintentos = "LedesmaParticipa-MetaReintentos"

# Retraso tras el inicio de sesión: le da tiempo a Windows/Ollama a terminar
# de arrancar antes de que el Motor intente su primer ciclo.
$DelayMotor = "PT30S"   # 30 segundos
$DelayPanel = "PT45S"   # levemente posterior al Motor

# Informe diario: disparo por horario fijo (no al iniciar sesión).
$HoraInformeDiario = "07:30"

# Publicación automática en Meta: franjas fijas del proyecto (ver
# motor_noticias/motor_editorial.py HORA_INFORME_DIARIO + HORARIOS_DEFAULT).
# MetaProgramacion se dispara dos veces (07:00 y 07:35) para tener el día
# preparado temprano y volver a incorporar el informe diario (que recién
# existe desde las 07:30) a su franja fija. MetaPlacas corre una vez, ya con
# la programación fresca. MetaPublicar se dispara una vez por cada franja
# fija (incluida una franja a las 07:35 para el informe diario, con margen
# tras su propia tarea). MetaReintentos corre cada 30 minutos durante el
# horario de publicación.
$HorasMetaPublicar = @("07:35", "09:30", "11:30", "13:30", "15:30", "17:30", "19:00", "20:30", "21:30", "22:30")

# Reintentos ante fallo: 3 intentos, cada 2 minutos - evita "restart storms"
# sin dejar de recuperarse ante un fallo puntual. Misma política para las
# tres tareas.
$RestartCount = 3
$RestartInterval = (New-TimeSpan -Minutes 2)

$triggerMotor = New-ScheduledTaskTrigger -AtLogOn
$triggerMotor.Delay = $DelayMotor

$triggerPanel = New-ScheduledTaskTrigger -AtLogOn
$triggerPanel.Delay = $DelayPanel

# -StartWhenAvailable (en $settings, compartido) hace que si la notebook
# está apagada/dormida a las 07:30, la tarea se dispare apenas vuelva a
# estar disponible en vez de saltearse el día.
$triggerInforme = New-ScheduledTaskTrigger -Daily -At $HoraInformeDiario

$triggerMetaProgramacion = @(
    (New-ScheduledTaskTrigger -Daily -At "07:00"),
    (New-ScheduledTaskTrigger -Daily -At "07:35")
)
$triggerMetaPlacas = New-ScheduledTaskTrigger -Daily -At "07:40"
$triggerMetaPublicar = foreach ($hora in $HorasMetaPublicar) { New-ScheduledTaskTrigger -Daily -At $hora }
$triggerMetaReintentos = New-ScheduledTaskTrigger -Once -At "08:00" `
    -RepetitionInterval (New-TimeSpan -Minutes 30) -RepetitionDuration (New-TimeSpan -Hours 16)

$accionMotor = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$(Join-Path $PSScriptRoot 'start_motor.ps1')`"" `
    -WorkingDirectory $root

$accionPanel = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$(Join-Path $PSScriptRoot 'start_panel.ps1')`"" `
    -WorkingDirectory $root

$accionInforme = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$(Join-Path $PSScriptRoot 'start_informe_diario.ps1')`"" `
    -WorkingDirectory $root

$accionMetaProgramacion = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$(Join-Path $PSScriptRoot 'start_meta_programacion.ps1')`"" `
    -WorkingDirectory $root

$accionMetaPlacas = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$(Join-Path $PSScriptRoot 'start_meta_placas.ps1')`"" `
    -WorkingDirectory $root

$accionMetaPublicar = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$(Join-Path $PSScriptRoot 'start_meta_publicar.ps1')`"" `
    -WorkingDirectory $root

$accionMetaReintentos = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$(Join-Path $PSScriptRoot 'start_meta_reintentos.ps1')`"" `
    -WorkingDirectory $root

# MultipleInstances IgnoreNew: si la tarea ya está corriendo, Task Scheduler
# no arranca una segunda instancia (además del lock propio del Motor).
# ExecutionTimeLimit cero: no hay límite de tiempo de ejecución. Se
# reutilizan estos mismos $settings para las siete tareas (Motor, Panel,
# Informe Diario): misma política de reintentos/instancia única/duración.
$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -RestartCount $RestartCount `
    -RestartInterval $RestartInterval `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -StartWhenAvailable `
    -DontStopOnIdleEnd

# LogonType Interactive + RunLevel Limited: corre bajo la sesión del usuario
# actual, sin privilegios elevados y sin necesidad de guardar contraseña.
# También reutilizado por las siete tareas.
$principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive `
    -RunLevel Limited

Register-ScheduledTask -TaskName $TareaMotor -Trigger $triggerMotor -Action $accionMotor -Settings $settings -Principal $principal -Force | Out-Null
Register-ScheduledTask -TaskName $TareaPanel -Trigger $triggerPanel -Action $accionPanel -Settings $settings -Principal $principal -Force | Out-Null
Register-ScheduledTask -TaskName $TareaInforme -Trigger $triggerInforme -Action $accionInforme -Settings $settings -Principal $principal -Force | Out-Null
Register-ScheduledTask -TaskName $TareaMetaProgramacion -Trigger $triggerMetaProgramacion -Action $accionMetaProgramacion -Settings $settings -Principal $principal -Force | Out-Null
Register-ScheduledTask -TaskName $TareaMetaPlacas -Trigger $triggerMetaPlacas -Action $accionMetaPlacas -Settings $settings -Principal $principal -Force | Out-Null
Register-ScheduledTask -TaskName $TareaMetaPublicar -Trigger $triggerMetaPublicar -Action $accionMetaPublicar -Settings $settings -Principal $principal -Force | Out-Null
Register-ScheduledTask -TaskName $TareaMetaReintentos -Trigger $triggerMetaReintentos -Action $accionMetaReintentos -Settings $settings -Principal $principal -Force | Out-Null

Write-Log -LogFile "startup.log" -Mensaje "install_tasks.ps1: tareas '$TareaMotor', '$TareaPanel', '$TareaInforme', '$TareaMetaProgramacion', '$TareaMetaPlacas', '$TareaMetaPublicar' y '$TareaMetaReintentos' registradas (retraso ${DelayMotor}/${DelayPanel}, informe diario ${HoraInformeDiario}, publicacion Meta en $($HorasMetaPublicar -join ', '), reintentos $RestartCount cada $($RestartInterval.TotalMinutes) min)."

Write-Host "Tareas registradas:"
Write-Host "  - $TareaMotor (retraso $DelayMotor tras inicio de sesión)"
Write-Host "  - $TareaPanel (retraso $DelayPanel tras inicio de sesión)"
Write-Host "  - $TareaInforme (diaria a las $HoraInformeDiario)"
Write-Host "  - $TareaMetaProgramacion (diaria a las 07:00 y 07:35)"
Write-Host "  - $TareaMetaPlacas (diaria a las 07:40)"
Write-Host "  - $TareaMetaPublicar (diaria en $($HorasMetaPublicar -join ', '))"
Write-Host "  - $TareaMetaReintentos (cada 30 minutos desde las 08:00, por 16 horas)"
Write-Host ""
Write-Host "Verificá con: scripts\windows\status.ps1"
Write-Host "Para iniciarlas ahora sin esperar el próximo disparo:"
Write-Host "  Start-ScheduledTask -TaskName '$TareaMotor'"
Write-Host "  Start-ScheduledTask -TaskName '$TareaPanel'"
Write-Host "  Start-ScheduledTask -TaskName '$TareaInforme'"
Write-Host "  Start-ScheduledTask -TaskName '$TareaMetaProgramacion'"
Write-Host "  Start-ScheduledTask -TaskName '$TareaMetaPlacas'"
Write-Host "  Start-ScheduledTask -TaskName '$TareaMetaPublicar'"
Write-Host "  Start-ScheduledTask -TaskName '$TareaMetaReintentos'"
