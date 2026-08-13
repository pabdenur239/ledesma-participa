# common.ps1 - funciones y rutas compartidas por todos los scripts de
# producción de Ledesma Participa en Windows. Nunca hardcodea la ruta del
# proyecto ni del intérprete Python: ambas se resuelven dinámicamente a
# partir de la ubicación de este mismo archivo (scripts/windows/), así el
# repo puede clonarse en cualquier ruta sin tocar los scripts.

$Script:ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$Script:LogsDir = Join-Path $Script:ProjectRoot "logs"

function Get-ProjectRoot {
    return $Script:ProjectRoot
}

function Get-ProjectPython {
    <#
    Resuelve el intérprete Python real del proyecto, sin asumir una ruta
    fija:
    1. .venv\Scripts\python.exe dentro del proyecto, si existe;
    2. si no, 'python' disponible en PATH.
    Lanza un error claro si no se encuentra ninguno.
    #>
    $venvPython = Join-Path $Script:ProjectRoot ".venv\Scripts\python.exe"
    if (Test-Path $venvPython) {
        return $venvPython
    }
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) {
        return $cmd.Source
    }
    throw "No se encontró ningún intérprete Python (ni .venv\Scripts\python.exe ni 'python' en PATH)."
}

function Write-Log {
    <#
    Escribe una línea con fecha/hora en logs/<LogFile>. Rotación simple: si
    el archivo supera ~5 MB se archiva como <LogFile>.1 (se pisa el anterior
    .1 si ya existía) y se empieza uno nuevo - evita crecimiento infinito
    sin infraestructura de logging adicional.

    Motor y Panel pueden arrancar casi al mismo tiempo y escribir en el
    mismo logs\startup.log. Se serializa la escritura entre procesos con un
    Mutex con nombre (System.Threading.Mutex, solo .NET estándar, sin
    dependencias externas) exclusivo por archivo de log, y además se
    reintenta unas pocas veces con espera corta y creciente ante un bloqueo
    momentáneo puntual. Cualquier otro error (permisos, disco lleno
    persistente, ruta inválida) se sigue propagando tal cual tras agotar
    los reintentos: nunca se oculta silenciosamente.
    #>
    param(
        [Parameter(Mandatory = $true)][string]$LogFile,
        [Parameter(Mandatory = $true)][string]$Mensaje,
        [string]$Nivel = "INFO",
        [int]$MaxIntentos = 5,
        [int]$EsperaBaseMilisegundos = 100,
        [int]$EsperaMutexMilisegundos = 5000
    )
    if (-not (Test-Path $Script:LogsDir)) {
        New-Item -ItemType Directory -Path $Script:LogsDir -Force | Out-Null
    }
    $ruta = Join-Path $Script:LogsDir $LogFile
    $linea = "{0} [{1}] {2}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Nivel, $Mensaje

    # Nombre de mutex único y estable por ruta de archivo (hash hex: sin
    # caracteres especiales que un nombre de mutex no admite).
    $md5 = [System.Security.Cryptography.MD5]::Create()
    try {
        $hashBytes = $md5.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($ruta))
    } finally {
        $md5.Dispose()
    }
    $hashHex = ([System.BitConverter]::ToString($hashBytes)) -replace '-', ''
    $mutex = New-Object System.Threading.Mutex($false, "Local\LedesmaParticipa-Log-$hashHex")

    $tieneMutex = $false
    try {
        try {
            $tieneMutex = $mutex.WaitOne($EsperaMutexMilisegundos)
        } catch [System.Threading.AbandonedMutexException] {
            # El proceso anterior que lo tenía terminó sin liberarlo
            # (p.ej. cierre inesperado): igual se obtiene el mutex.
            $tieneMutex = $true
        }

        for ($intento = 1; $intento -le $MaxIntentos; $intento++) {
            try {
                if (Test-Path $ruta) {
                    $tamanoMB = (Get-Item $ruta).Length / 1MB
                    if ($tamanoMB -gt 5) {
                        $rotado = "$ruta.1"
                        if (Test-Path $rotado) { Remove-Item $rotado -Force }
                        Rename-Item $ruta $rotado
                    }
                }
                Add-Content -Path $ruta -Value $linea -Encoding utf8 -ErrorAction Stop
                return
            } catch [System.IO.IOException] {
                if ($intento -ge $MaxIntentos) {
                    throw
                }
                Start-Sleep -Milliseconds ($EsperaBaseMilisegundos * $intento)
            }
        }
    } finally {
        if ($tieneMutex) {
            $mutex.ReleaseMutex()
        }
        $mutex.Dispose()
    }
}
