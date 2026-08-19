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
$TareaMetaUrgentes = "LedesmaParticipa-MetaUrgentes"
$TareaSitioWeb = "LedesmaParticipa-SitioWeb"

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
# tras su propia tarea, y una por hora entre las 09:00 y las 22:00 por
# cascada). MetaReintentos corre cada 30 minutos durante el horario de
# publicación.
$HorasMetaPublicar = @(
    "07:35", "09:00", "10:00", "11:00", "12:00", "13:00", "14:00", "15:00",
    "16:00", "17:00", "18:00", "19:00", "20:00", "21:00", "22:00"
)

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
# -Daily no admite -RepetitionInterval/-RepetitionDuration directamente
# (conjunto de parámetros ambiguo) y el trigger resultante no trae un
# objeto Repetition editable por defecto: se arma explícitamente como
# instancia CIM y se asigna. Mismo resultado que antes (repetición
# intradía), pero ahora recurrente todos los días en vez de una sola vez
# el día de alta (16/8).
function New-PatronRepeticion([TimeSpan]$Intervalo, [TimeSpan]$Duracion) {
    $clase = Get-CimClass -ClassName MSFT_TaskRepetitionPattern -Namespace Root/Microsoft/Windows/TaskScheduler
    $patron = New-CimInstance -CimClass $clase -ClientOnly
    $patron.Interval = [System.Xml.XmlConvert]::ToString($Intervalo)
    $patron.Duration = [System.Xml.XmlConvert]::ToString($Duracion)
    $patron.StopAtDurationEnd = $true
    return $patron
}

# Arranca en :10 (no en punto ni en :00/:30) para que sus disparos
# recurrentes (":10", ":40") nunca caigan en el mismo minuto que una
# franja fija de MetaPublicar (siempre en punto) ni que MetaUrgentes
# (":05"/":20"/":35"/":50") - evita la ráfaga de publicaciones
# simultáneas de distintas tareas vista el 18/8.
$triggerMetaReintentos = New-ScheduledTaskTrigger -Daily -At "08:10"
$triggerMetaReintentos.Repetition = New-PatronRepeticion (New-TimeSpan -Minutes 30) (New-TimeSpan -Hours 16)

# MetaUrgentes: último momento local/departamental no debe esperar la
# franja fija más cercana (hasta una hora de diferencia con el nuevo
# calendario horario). Se revisa cada 15 minutos durante el horario de
# publicación. Arranca en :50 (no en punto) por el mismo motivo que
# MetaReintentos: sus disparos (":05"/":20"/":35"/":50") nunca coinciden
# con una franja fija de MetaPublicar.
$triggerMetaUrgentes = New-ScheduledTaskTrigger -Daily -At "07:50"
$triggerMetaUrgentes.Repetition = New-PatronRepeticion (New-TimeSpan -Minutes 15) (New-TimeSpan -Hours 15)

# SitioWeb: regenera docs/ (HTML estático) reflejando lo que el motor ya
# publicó, sin volver a procesar ni redactar nada (solo lectura sobre la
# base). Corre cada 15 minutos, con 5 minutos de margen sobre MetaUrgentes,
# para que la web quede al día con lo publicado en cada pasada.
$triggerSitioWeb = New-ScheduledTaskTrigger -Daily -At "07:50"
$triggerSitioWeb.Repetition = New-PatronRepeticion (New-TimeSpan -Minutes 15) (New-TimeSpan -Hours 15)

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

$accionMetaUrgentes = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$(Join-Path $PSScriptRoot 'start_meta_urgentes.ps1')`"" `
    -WorkingDirectory $root

$accionSitioWeb = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$(Join-Path $PSScriptRoot 'start_sitio_web.ps1')`"" `
    -WorkingDirectory $root

# MultipleInstances IgnoreNew: si la tarea ya está corriendo, Task Scheduler
# no arranca una segunda instancia (además del lock propio del Motor).
# ExecutionTimeLimit cero: no hay límite de tiempo de ejecución. Se
# reutilizan estos mismos $settings para las siete tareas (Motor, Panel,
# Informe Diario): misma política de reintentos/instancia única/duración.
# WakeToRun: despierta la notebook desde suspensión/espera moderna para
# disparar a horario exacto, en vez de depender de StartWhenAvailable
# (que solo recupera una vez que la notebook ya volvió sola). Batería sin
# restricción (-AllowStartIfOnBatteries -DontStopIfGoingOnBatteries): antes
# cualquier tarea se negaba a arrancar o se detenía a mitad de camino si no
# había cargador conectado, sin relación con si la notebook estaba
# encendida.
$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -RestartCount $RestartCount `
    -RestartInterval $RestartInterval `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -StartWhenAvailable `
    -DontStopOnIdleEnd `
    -RunOnlyIfNetworkAvailable `
    -WakeToRun `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

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
Register-ScheduledTask -TaskName $TareaMetaUrgentes -Trigger $triggerMetaUrgentes -Action $accionMetaUrgentes -Settings $settings -Principal $principal -Force | Out-Null
Register-ScheduledTask -TaskName $TareaSitioWeb -Trigger $triggerSitioWeb -Action $accionSitioWeb -Settings $settings -Principal $principal -Force | Out-Null

Write-Log -LogFile "startup.log" -Mensaje "install_tasks.ps1: tareas '$TareaMotor', '$TareaPanel', '$TareaInforme', '$TareaMetaProgramacion', '$TareaMetaPlacas', '$TareaMetaPublicar', '$TareaMetaReintentos', '$TareaMetaUrgentes' y '$TareaSitioWeb' registradas (retraso ${DelayMotor}/${DelayPanel}, informe diario ${HoraInformeDiario}, publicacion Meta en $($HorasMetaPublicar -join ', '), reintentos $RestartCount cada $($RestartInterval.TotalMinutes) min, urgentes cada 15 min, sitio web cada 15 min)."

Write-Host "Tareas registradas:"
Write-Host "  - $TareaMotor (retraso $DelayMotor tras inicio de sesión)"
Write-Host "  - $TareaPanel (retraso $DelayPanel tras inicio de sesión)"
Write-Host "  - $TareaInforme (diaria a las $HoraInformeDiario)"
Write-Host "  - $TareaMetaProgramacion (diaria a las 07:00 y 07:35)"
Write-Host "  - $TareaMetaPlacas (diaria a las 07:40)"
Write-Host "  - $TareaMetaPublicar (diaria en $($HorasMetaPublicar -join ', '))"
Write-Host "  - $TareaMetaReintentos (cada 30 minutos desde las 08:10, por 16 horas, maximo 1 pendiente por corrida)"
Write-Host "  - $TareaMetaUrgentes (cada 15 minutos desde las 07:50, por 15 horas, maximo 1 pendiente por corrida)"
Write-Host "  - $TareaSitioWeb (cada 15 minutos desde las 07:50, por 15 horas)"
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
Write-Host "  Start-ScheduledTask -TaskName '$TareaMetaUrgentes'"
Write-Host "  Start-ScheduledTask -TaskName '$TareaSitioWeb'"
