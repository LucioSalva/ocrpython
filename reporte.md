# Reporte / Bitacora del proyecto OCR

## Estado actual (2026-04-28)

El repositorio contiene tres modos de operacion coexistiendo en la
misma raiz:

1. **Stack web Docker Compose** - backend FastAPI + frontend PHP +
   PostgreSQL. Ya existia. Vive en `backend/`, `frontend/`, `db/`,
   `docker-compose.yml`. Documentado en `README_LEGACY.md`.
2. **CLI Python con Tesseract** - `main.py` + `src/`, con deteccion de
   bloques negros y debug visual. Modo experimental. Documentado en
   `README_CLI.md`.
3. **OCR local con Docker + OCRmyPDF** (NUEVO, agregado en esta iteracion)
   - es el modo recomendado y queda documentado como "Modo 1" en el nuevo
   `README.md`.

Los tres modos comparten las carpetas `input/` (entrada) y `output/`
(resultados), pero generan estructuras de salida distintas:

- Modo CLI Python: `output/<nombre>/{paginas,bloques_negros,debug}/`
- Modo Docker: `output/<nombre>/{salida_ocr.pdf, texto_extraido_layout.txt,
  reporte_ocr.txt, run.log}`

No hay colision: los archivos del modo Docker tienen nombres distintos
a los del CLI Python.

## Que se hizo en esta iteracion

- Se respaldo el `README.md` previo como `README_LEGACY.md`.
- Se reescribio `README.md` para documentar los tres modos y dejar el
  modo Docker como "principal".
- Se agregaron los siguientes scripts en `scripts/`:
  - `verificar_dependencias.ps1` - preflight Docker / imagen / pdftotext.
  - `ocr_local.ps1` - entrypoint principal del nuevo modo.
  - `ocr_local.bat` - wrapper doble-click.
- No se toco ningun archivo del stack web ni del CLI Python.

## Decisiones tecnicas

### Imagen Docker `jbarlow83/ocrmypdf` (no `ocrmypdf/ocrmypdf`)

Es la imagen oficial moderna mantenida por el autor de OCRmyPDF, ya
incluye Tesseract con multiples idiomas, ghostscript, qpdf, unpaper y
**Poppler** (de ahi que sirva como fallback para `pdftotext`).

### Bind de la raiz del proyecto, no de subcarpetas

El contenedor monta la raiz (`-v <ProjectRoot>:/data`) en lugar de
montar `input/` y `output/` por separado. Esto simplifica:

- soportar `-Pdf` apuntando a un PDF que NO esta en `input/`,
- correr el fallback pdftotext sobre `output/<x>/salida_ocr.pdf` con
  el mismo bind,
- evitar problemas con paths con espacios en Windows.

Restriccion: el PDF de entrada debe vivir bajo la raiz del proyecto.
Si alguien pasa una ruta absoluta fuera del proyecto, el script aborta
ese PDF con un error claro.

### Fallback de `pdftotext` dentro del contenedor

`pdftotext` en host es opcional. La imagen `jbarlow83/ocrmypdf` ya
incluye Poppler, asi que el script invoca:

```
docker run --rm -v <root>:/data --entrypoint pdftotext jbarlow83/ocrmypdf:latest -layout <in> <out>
```

Esto evita pedir al usuario instalar Poppler en Windows (que puede
ser engorroso por el manejo de PATH).

### Reintento sin `--clean`

`--clean` requiere `unpaper`. La imagen jbarlow83 lo trae, pero por
robustez si el primer intento falla con `--clean`, se reintenta sin
el flag y se anota en `run.log`.

### Codigos de salida OCRmyPDF

- 0: ok.
- 6: DPI inferior - se loggea claramente.
- 8: salida no es PDF valido - se loggea claramente.

El script no detiene el lote ante un fallo aislado: continua con el
siguiente PDF y reporta el conteo final (procesados / saltados / fallidos).

### Heuristica de calidad y "secciones a revisar"

- Calidad: caracteres por pagina (>=1500 alta, >=500 media, resto baja).
- Revisar:
  - Pagina con < 100 chars en el txt -> probable OCR debil.
  - Run de >= 5 caracteres no imprimibles -> posibles sellos/firmas
    superpuestos.

Son indicadores groseros, suficientes para decirle al humano "mira aqui".

### Codificacion de archivos

- `.ps1` se guardan con UTF-8.
- `.txt` y `.log` de salida: UTF-8 sin BOM.
- Sin emojis en codigo ni docs.

## Limitaciones conocidas

- Solo PDF de entrada (no imagenes sueltas; OCRmyPDF puede pero
  el script no lo expone de momento).
- Si Docker Desktop no esta corriendo, el script aborta limpio pero
  no intenta levantar Docker Desktop por el usuario.
- En la primera ejecucion, la imagen se descarga (~1 GB). Es lento.
  Sugerencia: correr `.\scripts\ocr_local.ps1 -PullImage` una vez
  fuera de horario de trabajo.
- No se verifica firma digital del PDF original ni se preserva.
- Heuristica de "secciones a revisar" es muy simple: no detecta tablas
  fragmentadas ni columnas pegadas.

## Proximos pasos sugeridos

1. **Validacion sobre el corpus real** - correr el lote sobre los
   documentos catastrales y municipales y revisar el reporte de calidad.
2. **Mejorar la heuristica de revision** - hoy es chars/pagina y runs
   no imprimibles. Se podria agregar deteccion de filas con > X
   tokens cortos consecutivos (indicio de tabla mal extraida).
3. **Modo `-Cloud` con Azure Document Intelligence** - documentado en
   README pero NO implementado. Si se activa, debe ser via flag
   explicito y requerir `.env.cloud` separado (privacy by default).
4. **Integracion con el stack web** - exponer el pipeline como un
   endpoint del backend FastAPI para que el frontend PHP pueda subir
   PDFs y obtener `salida_ocr.pdf` + `reporte_ocr.txt`. Hoy estan
   desconectados.
5. **CI minimo** - una prueba que monte un PDF chico y valide que
   `salida_ocr.pdf` se genera y `reporte_ocr.txt` reporta > 0 chars.
