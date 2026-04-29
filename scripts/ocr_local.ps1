<#
.SYNOPSIS
    Pipeline OCR local basada en Docker + OCRmyPDF + Poppler.

.DESCRIPTION
    Procesa uno o varios PDFs escaneados ubicados en input/ usando la
    imagen Docker jbarlow83/ocrmypdf. Por cada PDF genera en
    output/<nombre>/:
      - salida_ocr.pdf            PDF con capa de texto buscable.
      - texto_extraido_layout.txt Texto plano (-layout) preservando columnas.
      - reporte_ocr.txt           Metricas y secciones a revisar.
      - run.log                   Bitacora completa de docker run.

    El bind monta input/ como solo-lectura y output/ como lectura-escritura
    en rutas separadas dentro del contenedor (/data/input, /data/output).
    Si pdftotext NO esta en el host, se invoca dentro del contenedor
    Docker (la imagen jbarlow83 incluye Poppler).

.PARAMETER Pdf
    Ruta a un PDF especifico bajo input/ (relativa o absoluta dentro de
    input/). Si se omite, procesa todos los *.pdf de InputDir.

.PARAMETER InputDir
    Carpeta de entrada relativa a la raiz del proyecto. Default: input.

.PARAMETER OutputDir
    Carpeta de salida relativa a la raiz del proyecto. Default: output.

.PARAMETER Lang
    Idioma(s) Tesseract para OCRmyPDF (ej. spa, eng, spa+eng). Default: spa.

.PARAMETER Force
    Reprocesa PDFs aunque ya exista salida_ocr.pdf.

.PARAMETER NoClean
    No usa --clean en OCRmyPDF (saltar unpaper).

.PARAMETER PullImage
    Ejecuta 'docker pull' antes de procesar.

.PARAMETER DockerImage
    Imagen Docker a utilizar. Default: jbarlow83/ocrmypdf:latest.

.PARAMETER PerPdfTimeoutSec
    Timeout en segundos para cada 'docker run'. Default: 600.

.EXAMPLE
    .\scripts\ocr_local.ps1
    .\scripts\ocr_local.ps1 -Pdf input/foo.pdf -Lang spa+eng -Force
    .\scripts\ocr_local.ps1 -PullImage
#>

[CmdletBinding()]
param(
    [string]$Pdf = "",
    [string]$InputDir = "input",
    [string]$OutputDir = "output",
    [string]$Lang = "spa",
    [switch]$Force,
    [switch]$NoClean,
    [switch]$PullImage,
    [string]$DockerImage = "jbarlow83/ocrmypdf:latest",
    [int]$PerPdfTimeoutSec = 600
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Continue'

# ---------- helpers ----------
function Write-Info { param([string]$Message) Write-Output ("[INFO ] {0}" -f $Message) }
function Write-Ok   { param([string]$Message) Write-Output ("[OK   ] {0}" -f $Message) }
function Write-Warn { param([string]$Message) Write-Output ("[WARN ] {0}" -f $Message) }
function Write-Err  { param([string]$Message) Write-Output ("[ERROR] {0}" -f $Message) }

function Convert-WinPathToDocker {
    param([Parameter(Mandatory)][string]$WinPath)
    return ($WinPath -replace '\\','/')
}

function Save-Utf8 {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Content
    )
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Content, $utf8NoBom)
}

function Append-Utf8 {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Content
    )
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    if (-not (Test-Path -LiteralPath $Path)) {
        [System.IO.File]::WriteAllText($Path, $Content, $utf8NoBom)
    } else {
        [System.IO.File]::AppendAllText($Path, $Content, $utf8NoBom)
    }
}

function Read-Utf8 {
    param([Parameter(Mandatory)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return "" }
    return [System.IO.File]::ReadAllText($Path, [System.Text.Encoding]::UTF8)
}

# Run an external process with a timeout. Returns [pscustomobject] with
# ExitCode, Stdout, Stderr, TimedOut. Kills the process tree on timeout.
function Invoke-WithTimeout {
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [Parameter(Mandatory)][string[]]$ArgumentList,
        [int]$TimeoutSec = 600
    )
    $stdoutTmp = [System.IO.Path]::GetTempFileName()
    $stderrTmp = [System.IO.Path]::GetTempFileName()
    try {
        $proc = Start-Process -FilePath $FilePath -ArgumentList $ArgumentList `
            -NoNewWindow -PassThru `
            -RedirectStandardOutput $stdoutTmp `
            -RedirectStandardError  $stderrTmp
        if (-not $proc.WaitForExit($TimeoutSec * 1000)) {
            try { $proc.Kill($true) } catch { try { $proc.Kill() } catch { } }
            return [pscustomobject]@{
                ExitCode = -1
                Stdout   = (Read-Utf8 -Path $stdoutTmp)
                Stderr   = (Read-Utf8 -Path $stderrTmp) + "`r`n[timeout tras $TimeoutSec s]"
                TimedOut = $true
            }
        }
        return [pscustomobject]@{
            ExitCode = $proc.ExitCode
            Stdout   = (Read-Utf8 -Path $stdoutTmp)
            Stderr   = (Read-Utf8 -Path $stderrTmp)
            TimedOut = $false
        }
    } finally {
        Remove-Item -LiteralPath $stdoutTmp -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $stderrTmp -Force -ErrorAction SilentlyContinue
    }
}

# ---------- resolver raiz del proyecto ----------
$ProjectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
Write-Info ("Raiz del proyecto: {0}" -f $ProjectRoot)

$InputPath  = (Resolve-Path -LiteralPath (Join-Path $ProjectRoot $InputDir) -ErrorAction SilentlyContinue)
if (-not $InputPath) {
    Write-Err ("Carpeta de entrada no existe: {0}" -f (Join-Path $ProjectRoot $InputDir))
    exit 1
}
$InputPath = $InputPath.Path

$OutputPath = Join-Path $ProjectRoot $OutputDir
if (-not (Test-Path -LiteralPath $OutputPath)) {
    New-Item -ItemType Directory -Path $OutputPath -Force | Out-Null
}
$OutputPath = (Resolve-Path -LiteralPath $OutputPath).Path

# ---------- preflight (verificar dependencias) ----------
$Verifier = Join-Path $PSScriptRoot 'verificar_dependencias.ps1'
if (Test-Path -LiteralPath $Verifier) {
    Write-Info "Ejecutando verificador de dependencias..."
    & $Verifier
    $verifierExit = $LASTEXITCODE
    if ($verifierExit -eq 1) {
        Write-Err "Faltan dependencias criticas (Docker). Abortando."
        exit 1
    }
} else {
    Write-Warn ("Verificador no encontrado en: {0}" -f $Verifier)
}

# ---------- pull opcional ----------
if ($PullImage) {
    Write-Info ("Descargando imagen Docker: {0}" -f $DockerImage)
    docker pull $DockerImage
    if ($LASTEXITCODE -ne 0) {
        Write-Err "Fallo 'docker pull'. Abortando."
        exit 1
    }
}

# ---------- detectar pdftotext en host ----------
$HostPdfToText = $null
$cmd = Get-Command pdftotext -ErrorAction SilentlyContinue
if ($cmd) {
    $HostPdfToText = $cmd.Source
    Write-Info ("pdftotext en host: {0}" -f $HostPdfToText)
} else {
    $progFiles = @(
        $env:ProgramFiles,
        ${env:ProgramFiles(x86)},
        (Join-Path $env:LOCALAPPDATA 'Programs')
    ) | Where-Object { $_ -and (Test-Path $_) }
    foreach ($base in $progFiles) {
        $dirs = Get-ChildItem -Path $base -Filter 'poppler*' -Directory -ErrorAction SilentlyContinue
        foreach ($d in $dirs) {
            $hit = Get-ChildItem -Path $d.FullName -Recurse -Filter 'pdftotext.exe' -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($hit) { $HostPdfToText = $hit.FullName; break }
        }
        if ($HostPdfToText) { break }
    }
    if ($HostPdfToText) {
        Write-Info ("pdftotext autodetectado: {0}" -f $HostPdfToText)
    } else {
        Write-Warn "pdftotext NO disponible en host. Se usara fallback dentro de Docker."
    }
}

# ---------- lista de PDFs a procesar ----------
[System.Collections.ArrayList]$Pdfs = @()
if ($Pdf -and $Pdf.Trim()) {
    $candidate = $Pdf
    if (-not [System.IO.Path]::IsPathRooted($candidate)) {
        $candidate = Join-Path $ProjectRoot $candidate
    }
    if (-not (Test-Path -LiteralPath $candidate)) {
        Write-Err ("PDF no encontrado: {0}" -f $candidate)
        exit 1
    }
    [void]$Pdfs.Add((Resolve-Path -LiteralPath $candidate).Path)
} else {
    $found = Get-ChildItem -LiteralPath $InputPath -Filter '*.pdf' -File -ErrorAction SilentlyContinue
    foreach ($f in $found) { [void]$Pdfs.Add($f.FullName) }
}

if ($Pdfs.Count -eq 0) {
    Write-Warn ("No hay PDFs para procesar en: {0}" -f $InputPath)
    Write-Info "Coloca tus PDFs en input/ y vuelve a ejecutar."
    exit 0
}

Write-Info ("PDFs detectados: {0}" -f $Pdfs.Count)
foreach ($p in $Pdfs) { Write-Output ("        - {0}" -f (Split-Path -Leaf $p)) }

# Bind separado: input solo-lectura, output lectura-escritura.
# El bind cubre solo las dos carpetas designadas, no toda la raiz del
# proyecto (mitiga symlink-escape y reduce blast radius en caso de PDF
# malicioso que pudiera intentar escribir fuera).
$InputBind  = ('{0}:/data/input:ro' -f $InputPath)
$OutputBind = ('{0}:/data/output:rw' -f $OutputPath)

# ---------- procesar uno por uno ----------
$Procesados = 0
$Saltados   = 0
$Fallidos   = 0

foreach ($pdfFull in $Pdfs) {
    $stopwatch = [System.Diagnostics.Stopwatch]::StartNew()

    $pdfBaseName = [System.IO.Path]::GetFileNameWithoutExtension($pdfFull)
    $pdfFileName = [System.IO.Path]::GetFileName($pdfFull)
    $outDirPdf   = Join-Path $OutputPath $pdfBaseName
    $outPdf      = Join-Path $outDirPdf 'salida_ocr.pdf'
    $outTxt      = Join-Path $outDirPdf 'texto_extraido_layout.txt'
    $outReport   = Join-Path $outDirPdf 'reporte_ocr.txt'
    $outLog      = Join-Path $outDirPdf 'run.log'

    Write-Output ""
    Write-Output ("================================================================")
    Write-Output (" Procesando: {0}" -f $pdfFileName)
    Write-Output ("================================================================")

    # Validar que el PDF este efectivamente bajo InputDir (no solo bajo
    # ProjectRoot). Esto evita procesar archivos sensibles del repo
    # (backend/.env, db/*, etc.).
    $pdfFullResolved = (Resolve-Path -LiteralPath $pdfFull).Path
    if (-not $pdfFullResolved.StartsWith($InputPath, [System.StringComparison]::OrdinalIgnoreCase)) {
        Write-Err ("El PDF debe estar bajo {0}, no en otra carpeta del proyecto." -f $InputPath)
        Write-Err ("  Ruta dada: {0}" -f $pdfFullResolved)
        $Fallidos++
        continue
    }
    if ([System.IO.Path]::GetExtension($pdfFullResolved).ToLowerInvariant() -ne '.pdf') {
        Write-Err ("El archivo no tiene extension .pdf: {0}" -f $pdfFullResolved)
        $Fallidos++
        continue
    }

    if (-not (Test-Path -LiteralPath $outDirPdf)) {
        New-Item -ItemType Directory -Path $outDirPdf -Force | Out-Null
    }

    if ((Test-Path -LiteralPath $outPdf) -and -not $Force) {
        Write-Warn ("Ya existe {0}. Usa -Force para regenerar. Saltando." -f $outPdf)
        $Saltados++
        continue
    }

    if ($Force) {
        foreach ($f in @($outPdf, $outTxt, $outReport, $outLog)) {
            if (Test-Path -LiteralPath $f) { Remove-Item -LiteralPath $f -Force -ErrorAction SilentlyContinue }
        }
    }

    # Bitacora con paths relativos (no filtra usuario en logs compartidos).
    $relInputForLog = $pdfFullResolved.Substring($InputPath.Length).TrimStart('\','/')
    Save-Utf8 -Path $outLog -Content (
        "Bitacora OCR local`r`n" +
        ("PDF: input/{0}`r`n" -f (Convert-WinPathToDocker $relInputForLog)) +
        ("Inicio: {0}`r`n" -f (Get-Date -Format 's')) +
        ("Imagen Docker: {0}`r`n" -f $DockerImage) +
        ("Idioma: {0}`r`n" -f $Lang) +
        ("Timeout (s): {0}`r`n" -f $PerPdfTimeoutSec) +
        "----- ----- ----- ----- ----- -----`r`n"
    )

    # Paths Docker: input/<rel>.pdf vive en /data/input/<rel>; salida en /data/output/<base>/.
    $relInDocker  = '/data/input/'  + (Convert-WinPathToDocker $relInputForLog)
    $relOutDocker = '/data/output/' + $pdfBaseName + '/salida_ocr.pdf'
    $relTxtDocker = '/data/output/' + $pdfBaseName + '/texto_extraido_layout.txt'

    # ---------- 1) OCRmyPDF ----------
    $useClean = -not $NoClean
    $ocrSuccess = $false
    $attempt = 0
    $lastExit = -1
    $lastStderr = ''

    while (-not $ocrSuccess -and $attempt -lt 2) {
        $attempt++
        $ocrArgs = @(
            'run','--rm',
            '-v', $InputBind,
            '-v', $OutputBind,
            $DockerImage,
            '--force-ocr','--deskew','--rotate-pages',
            '--language', $Lang,
            '--output-type','pdf'
        )
        if ($useClean) { $ocrArgs += '--clean' }
        $ocrArgs += @($relInDocker, $relOutDocker)

        Append-Utf8 -Path $outLog -Content ("`r`n--- docker run OCRmyPDF (intento {0}, clean={1}) ---`r`n" -f $attempt, $useClean)
        Append-Utf8 -Path $outLog -Content (("Args: " + ($ocrArgs -join ' ')) + "`r`n")

        Write-Info ("OCRmyPDF intento {0} (clean={1}, timeout={2}s)..." -f $attempt, $useClean, $PerPdfTimeoutSec)

        $r = Invoke-WithTimeout -FilePath 'docker' -ArgumentList $ocrArgs -TimeoutSec $PerPdfTimeoutSec
        $lastExit = $r.ExitCode
        $lastStderr = $r.Stderr

        Append-Utf8 -Path $outLog -Content ("--- stdout ---`r`n{0}`r`n--- stderr ---`r`n{1}`r`n--- exit: {2} (timedOut={3}) ---`r`n" -f $r.Stdout, $r.Stderr, $r.ExitCode, $r.TimedOut)

        if ($r.TimedOut) {
            Write-Err ("OCRmyPDF excedio el timeout de {0} s. Abortando este PDF." -f $PerPdfTimeoutSec)
            break
        }

        if ($r.ExitCode -eq 0) {
            $ocrSuccess = $true
            Write-Ok ("OCRmyPDF OK -> {0}" -f $outPdf)
            break
        }

        # Reintento sin --clean SOLO si hay evidencia de unpaper.
        $stderrLower = ($r.Stderr | Out-String).ToLowerInvariant()
        $unpaperHint = ($stderrLower -match 'unpaper') -or ($stderrLower -match 'failed to clean')
        if ($useClean -and $attempt -lt 2 -and $unpaperHint) {
            Write-Warn ("OCRmyPDF fallo por unpaper (--clean). Reintentando sin --clean...")
            $useClean = $false
            continue
        }

        Write-Err ("OCRmyPDF fallo con exit code {0}." -f $r.ExitCode)
        switch ($r.ExitCode) {
            2 { Write-Err "  -> codigo 2: argumentos invalidos. Revisa --language y la imagen." }
            4 { Write-Err "  -> codigo 4: PDF de entrada corrupto." }
            6 { Write-Err "  -> codigo 6: DPI inferior al minimo; revisa la calidad del escaneo." }
            8 { Write-Err "  -> codigo 8: archivo de salida no es un PDF valido." }
            default { }
        }
        break
    }

    if (-not $ocrSuccess) {
        $Fallidos++
        Append-Utf8 -Path $outLog -Content ("`r`nResultado: FALLIDO (exit={0})`r`n" -f $lastExit)
        continue
    }

    # ---------- 2) pdftotext (-layout) ----------
    $txtOk = $false

    if ($HostPdfToText) {
        Write-Info "Ejecutando pdftotext en host (-layout)..."
        $r = Invoke-WithTimeout -FilePath $HostPdfToText -ArgumentList @('-layout', $outPdf, $outTxt) -TimeoutSec $PerPdfTimeoutSec
        Append-Utf8 -Path $outLog -Content ("`r`n--- pdftotext host ---`r`nstdout: {0}`r`nstderr: {1}`r`nexit: {2} (timedOut={3})`r`n" -f $r.Stdout, $r.Stderr, $r.ExitCode, $r.TimedOut)
        if ($r.ExitCode -eq 0 -and (Test-Path -LiteralPath $outTxt)) { $txtOk = $true }
    }

    if (-not $txtOk) {
        Write-Info "Fallback: ejecutando pdftotext dentro del contenedor Docker..."
        $ttArgs = @(
            'run','--rm',
            '-v', $OutputBind,
            '--entrypoint','pdftotext',
            $DockerImage,
            '-layout', $relOutDocker, $relTxtDocker
        )
        Append-Utf8 -Path $outLog -Content ("`r`n--- docker run pdftotext (fallback) ---`r`n" + ("Args: " + ($ttArgs -join ' ')) + "`r`n")

        $r = Invoke-WithTimeout -FilePath 'docker' -ArgumentList $ttArgs -TimeoutSec $PerPdfTimeoutSec
        Append-Utf8 -Path $outLog -Content ("--- stdout ---`r`n{0}`r`n--- stderr ---`r`n{1}`r`n--- exit: {2} (timedOut={3}) ---`r`n" -f $r.Stdout, $r.Stderr, $r.ExitCode, $r.TimedOut)

        if ($r.ExitCode -eq 0 -and (Test-Path -LiteralPath $outTxt)) {
            $txtOk = $true
            Write-Ok ("pdftotext (Docker) OK -> {0}" -f $outTxt)
        } else {
            Write-Err ("pdftotext (Docker) fallo con exit code {0}." -f $r.ExitCode)
        }
    } else {
        Write-Ok ("pdftotext (host) OK -> {0}" -f $outTxt)
    }

    # ---------- 3) reporte_ocr.txt ----------
    $stopwatch.Stop()
    $elapsed = [math]::Round($stopwatch.Elapsed.TotalSeconds, 2)

    $sizeBytes = (Get-Item -LiteralPath $pdfFullResolved).Length

    $textRaw   = ''
    $lineCount = 0
    $wordCount = 0
    $charCount = 0
    $pageCount = 0
    $pagesText = @()

    if ($txtOk) {
        $textRaw = Read-Utf8 -Path $outTxt

        # paginas separadas por form-feed \f.
        $pagesText = $textRaw -split "`f"
        $pageCount = $pagesText.Count
        if ($pageCount -gt 0 -and -not ($pagesText[-1].Trim())) { $pageCount = $pageCount - 1 }
        if ($pageCount -lt 1) { $pageCount = 1 }

        $charCount = $textRaw.Length
        $lineCount = ($textRaw -split "`r?`n").Count
        $wordCount = (($textRaw -split '\s+') | Where-Object { $_ -ne '' }).Count
    }

    $charsPerPage = if ($pageCount -gt 0) { [int]($charCount / $pageCount) } else { 0 }
    $calidad =
        if ($charsPerPage -ge 1500) { 'alta' }
        elseif ($charsPerPage -ge 500) { 'media' }
        else { 'baja' }

    # Heuristica: paginas con poco texto o con runs largos de no-imprimibles.
    # El range valido cubre ASCII printable + Latin-1 con acentos (U+00C0-U+017F).
    $invalidRunRegex = [regex]::new('[^ -~À-ſ\r\n\t\f]{5,}')
    $revisar = @()
    $perPageMetrics = @()
    for ($i = 0; $i -lt $pagesText.Count; $i++) {
        $pg = $pagesText[$i]
        if ($null -eq $pg) { continue }
        $charsPg = $pg.Length
        $perPageMetrics += ("  Pagina {0}: {1} chars" -f ($i + 1), $charsPg)

        if ($charsPg -lt 100 -and $i -lt ($pagesText.Count - 1)) {
            $revisar += ("Pagina {0}: muy poco texto ({1} chars). OCR debil o pagina casi en blanco." -f ($i + 1), $charsPg)
        }

        $nonPrintRuns = $invalidRunRegex.Matches($pg)
        if ($nonPrintRuns.Count -gt 0) {
            $revisar += ("Pagina {0}: {1} run(s) de caracteres no imprimibles. Posibles sellos/firmas sobre texto." -f ($i + 1), $nonPrintRuns.Count)
        }
    }
    if ($revisar.Count -eq 0) { $revisar = @('(ninguna deteccion automatica)') }

    $report = New-Object System.Text.StringBuilder
    [void]$report.AppendLine("Reporte OCR local")
    [void]$report.AppendLine("==================")
    [void]$report.AppendLine(("PDF original ........... {0}" -f $pdfFileName))
    [void]$report.AppendLine(("PDF buscable ........... output/{0}/salida_ocr.pdf" -f $pdfBaseName))
    [void]$report.AppendLine(("Texto layout ........... output/{0}/texto_extraido_layout.txt" -f $pdfBaseName))
    [void]$report.AppendLine(("Tamano (bytes) ......... {0}" -f $sizeBytes))
    [void]$report.AppendLine(("Paginas (heuristica) ... {0}" -f $pageCount))
    [void]$report.AppendLine(("Idioma OCR ............. {0}" -f $Lang))
    [void]$report.AppendLine(("Tiempo total (s) ....... {0}" -f $elapsed))
    [void]$report.AppendLine(("Lineas extraidas ....... {0}" -f $lineCount))
    [void]$report.AppendLine(("Palabras extraidas ..... {0}" -f $wordCount))
    [void]$report.AppendLine(("Caracteres extraidos ... {0}" -f $charCount))
    [void]$report.AppendLine(("Chars / pagina ......... {0}" -f $charsPerPage))
    [void]$report.AppendLine(("Calidad probable ....... {0}" -f $calidad))
    [void]$report.AppendLine("")
    [void]$report.AppendLine("Caracteres por pagina")
    [void]$report.AppendLine("---------------------")
    if ($perPageMetrics.Count -eq 0) {
        [void]$report.AppendLine("  (sin texto extraido)")
    } else {
        foreach ($m in $perPageMetrics) { [void]$report.AppendLine($m) }
    }
    [void]$report.AppendLine("")
    [void]$report.AppendLine("Secciones a revisar manualmente")
    [void]$report.AppendLine("--------------------------------")
    foreach ($r2 in $revisar) { [void]$report.AppendLine(("- {0}" -f $r2)) }

    Save-Utf8 -Path $outReport -Content $report.ToString()
    Write-Ok ("Reporte -> {0}" -f $outReport)

    Append-Utf8 -Path $outLog -Content ("`r`nResultado: PROCESADO`r`nFin: {0}`r`nTiempo (s): {1}`r`n" -f (Get-Date -Format 's'), $elapsed)
    $Procesados++
}

# ---------- resumen final ----------
Write-Output ""
Write-Output "================================================================"
Write-Output " Resumen final"
Write-Output "================================================================"
Write-Output (" PDFs procesados ........ {0}" -f $Procesados)
Write-Output (" PDFs saltados .......... {0}" -f $Saltados)
Write-Output (" PDFs fallidos .......... {0}" -f $Fallidos)
Write-Output ""

if ($Fallidos -gt 0) { exit 1 }
exit 0
