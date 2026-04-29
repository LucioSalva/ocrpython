@echo off
REM ============================================================
REM  Wrapper doble-click para OCR local (Docker + OCRmyPDF).
REM  Invoca scripts\ocr_local.ps1 con politica de ejecucion bypass.
REM ============================================================

setlocal

set "SCRIPT_DIR=%~dp0"
set "PROJECT_ROOT=%SCRIPT_DIR%.."
set "INPUT_DIR=%PROJECT_ROOT%\input"

REM Conteo rapido de PDFs en input\
set "PDF_COUNT=0"
if exist "%INPUT_DIR%" (
    for %%F in ("%INPUT_DIR%\*.pdf") do (
        if exist "%%F" set /a PDF_COUNT+=1
    )
)

if "%PDF_COUNT%"=="0" (
    echo.
    echo No se encontraron archivos PDF en:
    echo     %INPUT_DIR%
    echo.
    echo Coloca tus PDFs en la carpeta input\ y vuelve a hacer doble click.
    echo.
    pause
    goto :eof
)

where powershell.exe >nul 2>&1
if errorlevel 1 (
    echo PowerShell no esta disponible en este sistema.
    pause
    endlocal
    exit /b 127
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%ocr_local.ps1" %*
set "EXITCODE=%ERRORLEVEL%"

echo.
if "%EXITCODE%"=="0" (
    echo Pipeline finalizado correctamente.
) else (
    echo Pipeline finalizado con codigo de salida %EXITCODE%.
)
echo.
pause
endlocal & exit /b %EXITCODE%
