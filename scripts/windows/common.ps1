# common.ps1 — funciones y rutas compartidas por todos los scripts de
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
    .1 si ya existía) y se empieza uno nuevo — evita crecimiento infinito
    sin infraestructura de logging adicional.
    #>
    param(
        [Parameter(Mandatory = $true)][string]$LogFile,
        [Parameter(Mandatory = $true)][string]$Mensaje,
        [string]$Nivel = "INFO"
    )
    if (-not (Test-Path $Script:LogsDir)) {
        New-Item -ItemType Directory -Path $Script:LogsDir -Force | Out-Null
    }
    $ruta = Join-Path $Script:LogsDir $LogFile

    if (Test-Path $ruta) {
        $tamanoMB = (Get-Item $ruta).Length / 1MB
        if ($tamanoMB -gt 5) {
            $rotado = "$ruta.1"
            if (Test-Path $rotado) { Remove-Item $rotado -Force }
            Rename-Item $ruta $rotado
        }
    }

    $linea = "{0} [{1}] {2}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Nivel, $Mensaje
    Add-Content -Path $ruta -Value $linea -Encoding utf8
}
