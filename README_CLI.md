# OCR CLI standalone

Herramienta de linea de comandos para extraer texto de PDFs escaneados de
documentos oficiales/municipales mexicanos. Renderiza paginas a alta
resolucion, detecta bloques oscuros con texto blanco (encabezados de
trámite tipicos), los invierte para leerlos, y combina ese OCR con el de
la pagina completa usando multi-PSM con scoring por palabras clave.

Esta CLI vive al lado del stack web del proyecto y **no toca** `backend/`,
`frontend/`, `db/`, ni `docker-compose.yml`.

## Pre-requisitos

- Python 3.11+ (probado en 3.14).
- Tesseract OCR instalado localmente.

### Tesseract en Windows

```powershell
winget install UB-Mannheim.TesseractOCR
```

El instalador de UB-Mannheim ya incluye `spa.traineddata`, asegurate de
**marcar el idioma espanol** en el wizard. Si no lo hiciste, descarga
`spa.traineddata` desde
<https://github.com/tesseract-ocr/tessdata> y copialo a:

```
C:\Program Files\Tesseract-OCR\tessdata\spa.traineddata
```

Verifica que aparece:

```powershell
& "C:\Program Files\Tesseract-OCR\tesseract.exe" --list-langs
```

Si `tesseract` no esta en el PATH, la CLI lo autodetecta en
`C:\Program Files\Tesseract-OCR\tesseract.exe` (y la variante x86). Si lo
instalaste en otra ruta, agregala al PATH y reinicia la terminal.

## Instalacion de dependencias Python

Las deps de la CLI estan en `requirements.txt` de la **raiz** del proyecto
(distinto al de `backend/`). En un venv aislado:

```powershell
cd C:\Users\lua22\Desktop\creacionSoftware\ocr
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Uso

```powershell
# Procesa un PDF especifico
python main.py --pdf "input/ASIGNACION-DE-CLAVE-CATASTRAL.pdf"

# Procesa todos los PDFs en input/
python main.py

# Mas calidad / idioma combinado
python main.py --pdf "input/foo.pdf" --dpi 500 --lang spa+eng

# Modo rapido (sin imagenes debug)
python main.py --no-debug

# Reprocesar aunque ya exista output
python main.py --force

# Logs detallados
$env:OCR_DEBUG="1"; python main.py
```

## Estructura de salida

Por cada PDF se crea `output/<nombre_sin_extension>/`:

```
output/<nombre>/
  texto_extraido.txt        # Texto final (formato anotado por pagina/bloque)
  run.log                    # Log detallado de la corrida
  paginas/
    pagina_01.png           # Pagina renderizada
    ...
  bloques_negros/
    pagina_01_bloque_01.png # Recortes invertidos / binarizados / 2.5x
    ...
  debug/                     # Solo si NO se paso --no-debug
    pagina_01_preprocesada.png
    pagina_01_mascara_bloques.png
    pagina_01_bloques_detectados.png  # Overlay con rectangulos rojos
```

`texto_extraido.txt`:

```
============================================================
ARCHIVO: <nombre>.pdf
============================================================

============================================================
PÁGINA 1
============================================================

[OCR GENERAL]
(psm=6)
<texto de la pagina completa>

[OCR DE BLOQUES NEGROS]
Bloques detectados: 7

[Bloque negro 1] (x=120, y=85, w=420, h=48) (psm=6)
REGISTRO MUNICIPAL DE TRÁMITES Y SERVICIOS
...
```

## Argumentos

| Flag         | Default | Descripcion                                          |
|--------------|---------|------------------------------------------------------|
| `--pdf PATH` | -       | PDF puntual; si se omite procesa todos `input/*.pdf` |
| `--dpi INT`  | 400     | DPI de renderizado de PyMuPDF                        |
| `--lang STR` | `spa`   | Idiomas Tesseract (`spa`, `spa+eng`, etc.)           |
| `--no-debug` | off     | Omite la carpeta `debug/` (mas rapido)               |
| `--force`    | off     | Regenera aunque ya exista la salida                  |

## Solucion de problemas

- **`No se encontro el binario de Tesseract`**: instala UB-Mannheim y
  reinicia la terminal, o agrega `C:\Program Files\Tesseract-OCR` al PATH.
- **`Falta(n) idioma(s) en Tesseract: ['spa']`**: descarga
  `spa.traineddata` y copialo a `tessdata/`. Tu version actual solo trae
  `eng` y `osd`.
- **`PDF cifrado o protegido por contrasena`**: la CLI no rompe contrasenas;
  desprotege el PDF previamente (`qpdf --decrypt input.pdf out.pdf`).
- **Resultados con basura**: prueba `--dpi 500` y/o `--lang spa+eng`.
- **PDF muy grande / consumo de RAM**: reduce `--dpi` a 300.
