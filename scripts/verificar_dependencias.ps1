<#
.SYNOPSIS
    Verifica las dependencias requeridas por la pipeline OCR local
    basada en Docker + OCRmyPDF + Poppler.

.DESCRIPTION
    Reporta el estado de:
      1. Docker (CLI + daemon)
      2. Imagen Docker jbarlow83/ocrmypdf (informativo, no hace pull)
      3. pdftotext (Poppler) en host (opcional gracias a fallback Docker)

    Codigos de salida:
      0  todas las dependencias criticas OK
      1  falta dependencia critica (Docker)
      2  solo faltan opcionales (pdftotext en host, imagen no descargada)

.NOTES
    Sin emojis. Salida ASCII: [OK], [FALTA], [WARN], [INFO].
#>

[CmdletBinding()]
param()

$ErrorActionPreference = 'Continue'

# ---------- helpers ----------
function Write-Status {
    param(
        [Parameter(Mandatory)][ValidateSet('OK','FALTA','WARN','INFO')] [string]$Tag,
        [Parameter(Mandatory)][string]$Message
    )
    Write-Output ("[{0}] {1}" -f $Tag, $Message)
}

function Test-CommandExists {
    param([Parameter(Mandatory)][string]$Name)
    $cmd = Get-Command $Name -ErrorAction SilentlyContinue
    return [bool]$cmd
}

# ---------- estado ----------
$dockerOk        = $false
$dockerDaemonOk  = $false
$imageOk         = $false
$pdftotextOk     = $false
$pdftotextSource = ''

Write-Output "==============================================="
Write-Output " Verificacion de dependencias - OCR local"
Write-Output "==============================================="

# ---------- 1) Docker CLI ----------
if (Test-CommandExists 'docker') {
    try {
        $ver = docker --version 2>$null
        Write-Status -Tag OK -Message ("Docker CLI: {0}" -f $ver)
        $dockerOk = $true
    } catch {
        Write-Status -Tag FALTA -Message "Docker CLI presente pero fallo al ejecutar 'docker --version'."
    }
} else {
    Write-Status -Tag FALTA -Message "Docker CLI no encontrado en PATH."
    Write-Output "         Instala Docker Desktop: https://www.docker.com/products/docker-desktop/"
}

# ---------- 2) Docker daemon ----------
if ($dockerOk) {
    # Una sola invocacion: capturamos stderr y el codigo, y reusamos el resultado.
    $serverVer = (docker info --format '{{.ServerVersion}}' 2>&1) | Select-Object -First 1
    if ($LASTEXITCODE -eq 0 -and $serverVer -and -not ($serverVer -match '^error|^Cannot|^Server')) {
        Write-Status -Tag OK -Message ("Docker daemon corriendo (server version: {0})" -f $serverVer)
        $dockerDaemonOk = $true
    } else {
        Write-Status -Tag FALTA -Message "Docker CLI presente pero el daemon NO esta corriendo."
        Write-Output "         Inicia Docker Desktop y espera a que el icono de la barra de tareas este verde."
    }
}

# ---------- 3) Imagen jbarlow83/ocrmypdf ----------
if ($dockerDaemonOk) {
    $null = docker image inspect jbarlow83/ocrmypdf:latest 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Status -Tag OK -Message "Imagen 'jbarlow83/ocrmypdf:latest' descargada."
        $imageOk = $true
    } else {
        Write-Status -Tag WARN -Message "Imagen 'jbarlow83/ocrmypdf:latest' NO descargada (opcional aqui)."
        Write-Output "         Para descargarla manualmente:"
        Write-Output "             docker pull jbarlow83/ocrmypdf:latest"
        Write-Output "         O ejecuta el script principal con el flag -PullImage:"
        Write-Output "             .\scripts\ocr_local.ps1 -PullImage"
    }
} else {
    Write-Status -Tag INFO -Message "Verificacion de imagen Docker omitida (daemon no disponible)."
}

# ---------- 4) pdftotext en host ----------
if (Test-CommandExists 'pdftotext') {
    $src = (Get-Command pdftotext).Source
    Write-Status -Tag OK -Message ("pdftotext disponible en host: {0}" -f $src)
    $pdftotextOk = $true
    $pdftotextSource = $src
} else {
    # Intento de autodeteccion de Poppler en rutas comunes de Windows.
    $candidatos = @()
    $progFiles = @(
        $env:ProgramFiles,
        ${env:ProgramFiles(x86)},
        (Join-Path $env:LOCALAPPDATA 'Programs')
    ) | Where-Object { $_ -and (Test-Path $_) }

    foreach ($base in $progFiles) {
        $candidatos += Get-ChildItem -Path $base -Filter 'poppler*' -Directory -ErrorAction SilentlyContinue
    }

    $exe = $null
    foreach ($dir in $candidatos) {
        $hit = Get-ChildItem -Path $dir.FullName -Recurse -Filter 'pdftotext.exe' -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($hit) { $exe = $hit.FullName; break }
    }

    if ($exe) {
        Write-Status -Tag OK -Message ("pdftotext autodetectado en: {0}" -f $exe)
        Write-Output "         (Considera anadir el directorio bin\ de Poppler a tu PATH)"
        $pdftotextOk = $true
        $pdftotextSource = $exe
    } else {
        Write-Status -Tag WARN -Message "pdftotext (Poppler) NO encontrado en host."
        Write-Output "         Es OPCIONAL: el script ocr_local.ps1 hace fallback ejecutando"
        Write-Output "         pdftotext dentro del contenedor Docker (la imagen jbarlow83 ya lo incluye)."
        Write-Output "         Para instalarlo en host:"
        Write-Output "           - Descarga: https://github.com/oschwartz10612/poppler-windows/releases"
        Write-Output "           - Anade la carpeta 'Library\bin' al PATH del usuario."
        Write-Output "           - O usa: winget install --id user.poppler"
    }
}

# ---------- resumen ----------
Write-Output ""
Write-Output "-----------------------------------------------"
Write-Output " Resumen"
Write-Output "-----------------------------------------------"
Write-Output (" Docker CLI .................. {0}" -f ($(if ($dockerOk)        { 'OK' } else { 'FALTA' })))
Write-Output (" Docker daemon ............... {0}" -f ($(if ($dockerDaemonOk)  { 'OK' } else { 'FALTA' })))
Write-Output (" Imagen jbarlow83/ocrmypdf ... {0}" -f ($(if ($imageOk)         { 'OK' } else { 'pendiente (no critica)' })))
Write-Output (" pdftotext (host) ............ {0}" -f ($(if ($pdftotextOk)     { 'OK' } else { 'no (fallback Docker activo)' })))

if (-not $dockerOk -or -not $dockerDaemonOk) {
    Write-Output ""
    Write-Output "Resultado: FALTAN dependencias criticas. Codigo de salida 1."
    exit 1
}

# El "fallback Docker" para pdftotext requiere que la imagen este descargada.
# Si NI la imagen NI pdftotext en host estan, entonces la pipeline no podra
# generar el .txt sin antes hacer 'docker pull'. Lo elevamos a critico.
if (-not $imageOk -and -not $pdftotextOk) {
    Write-Output ""
    Write-Output "Resultado: ni la imagen Docker ni pdftotext en host estan disponibles."
    Write-Output "Sin uno de los dos NO se podra extraer texto. Descarga la imagen primero:"
    Write-Output "    docker pull jbarlow83/ocrmypdf:latest"
    Write-Output "Codigo de salida 1."
    exit 1
}

if (-not $imageOk -or -not $pdftotextOk) {
    Write-Output ""
    Write-Output "Resultado: criticas OK; faltan opcionales. Codigo de salida 2."
    exit 2
}

Write-Output ""
Write-Output "Resultado: TODO OK. Codigo de salida 0."
exit 0
