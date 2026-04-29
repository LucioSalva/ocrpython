/* ==========================================================
   result.js - Render de la tarjeta de resultado:
   tabs Texto/Campos/Metadatos y barra de descargas.
   ========================================================== */
(function () {
  'use strict';

  // -------- DOM refs --------
  let elCard, elTextArea, elCopyBtn, elFieldsBody, elMetaList,
      elExportButtons, elExportPdf, elProcessAnother,
      elOriginalContainer, elOriginalEmpty, elOriginalLink,
      elOriginalTabBtn,
      elLayoutContainer, elLayoutEmpty, elLayoutLink;

  // Estado mostrado actualmente (para descargas).
  const state = {
    doc: null,
  };

  // -------- Formatters --------

  const dateFmt = new Intl.DateTimeFormat('es-MX', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  });

  function formatDate(value) {
    if (!value) return '—';
    const d = value instanceof Date ? value : new Date(value);
    if (isNaN(d.getTime())) return '—';
    return dateFmt.format(d).replace(',', ',');
  }

  function formatLanguage(code) {
    if (!code) return '—';
    const map = { es: 'Espanol', en: 'Ingles' };
    return map[String(code).toLowerCase()] || code;
  }

  function formatNativePdf(v) {
    if (v === true) return 'PDF nativo';
    if (v === false) return 'PDF escaneado';
    return '—';
  }

  function isLikelyDate(s) {
    if (typeof s !== 'string') return false;
    return /^\d{4}-\d{2}-\d{2}/.test(s);
  }

  function isLikelyNumber(v) {
    if (typeof v === 'number') return Number.isFinite(v);
    if (typeof v !== 'string') return false;
    return /^-?\d+(\.\d+)?$/.test(v.trim());
  }

  function formatFieldValue(v) {
    if (v === null || v === undefined || v === '') return null;
    if (typeof v === 'boolean') return v ? 'Si' : 'No';
    if (typeof v === 'object') {
      try { return JSON.stringify(v); } catch { return String(v); }
    }
    if (isLikelyNumber(v)) {
      const n = Number(v);
      if (Number.isInteger(n)) return new Intl.NumberFormat('es-MX').format(n);
      return new Intl.NumberFormat('es-MX', {
        minimumFractionDigits: 2,
        maximumFractionDigits: 6,
      }).format(n);
    }
    if (isLikelyDate(v)) {
      const d = new Date(v);
      if (!isNaN(d.getTime())) return formatDate(d);
    }
    return String(v);
  }

  // -------- Render --------

  function clearChildren(node) {
    while (node.firstChild) node.removeChild(node.firstChild);
  }

  function renderText(text) {
    elTextArea.value = text == null ? '' : String(text);
  }

  function renderFields(fields) {
    clearChildren(elFieldsBody);
    if (!fields || typeof fields !== 'object' || Array.isArray(fields) && !fields.length) {
      const tr = document.createElement('tr');
      const td = document.createElement('td');
      td.colSpan = 2;
      td.className = 'text-center text-muted';
      td.textContent = 'Sin campos.';
      tr.appendChild(td);
      elFieldsBody.appendChild(tr);
      return;
    }
    const entries = Array.isArray(fields)
      ? fields.map((it, i) => [it.key || it.name || `#${i}`, it.value])
      : Object.entries(fields);

    if (!entries.length) {
      const tr = document.createElement('tr');
      const td = document.createElement('td');
      td.colSpan = 2;
      td.className = 'text-center text-muted';
      td.textContent = 'Sin campos.';
      tr.appendChild(td);
      elFieldsBody.appendChild(tr);
      return;
    }

    entries.forEach(([k, v]) => {
      const tr = document.createElement('tr');
      const tdK = document.createElement('th');
      tdK.scope = 'row';
      tdK.className = 'fw-semibold';
      tdK.textContent = String(k);
      const tdV = document.createElement('td');
      const formatted = formatFieldValue(v);
      if (formatted == null) {
        tdV.textContent = '—';
        tdV.classList.add('field-empty');
      } else {
        tdV.textContent = formatted;
      }
      tr.appendChild(tdK);
      tr.appendChild(tdV);
      elFieldsBody.appendChild(tr);
    });
  }

  function appendMetaRow(parent, label, value) {
    const dt = document.createElement('dt');
    dt.className = 'col-sm-4';
    dt.textContent = label;
    const dd = document.createElement('dd');
    dd.className = 'col-sm-8';
    if (value == null || value === '') {
      dd.textContent = '—';
      dd.classList.add('field-empty');
    } else {
      dd.textContent = String(value);
    }
    parent.appendChild(dt);
    parent.appendChild(dd);
  }

  function renderMeta(doc) {
    clearChildren(elMetaList);
    appendMetaRow(elMetaList, 'Archivo original', doc.original_filename);
    appendMetaRow(elMetaList, 'Plantilla',
      (doc.template && (doc.template.name || doc.template.code)) || doc.template_code || '—');
    appendMetaRow(elMetaList, 'Idioma', formatLanguage(doc.language));
    appendMetaRow(elMetaList, 'Tipo', formatNativePdf(doc.is_native_pdf));
    appendMetaRow(elMetaList, 'Motor OCR', doc.ocr_engine || '—');
    appendMetaRow(elMetaList, 'Creado', formatDate(doc.created_at));
    appendMetaRow(elMetaList, 'Completado', formatDate(doc.completed_at));

    // Metadatos extra del documento si vienen.
    if (doc.metadata && typeof doc.metadata === 'object') {
      Object.entries(doc.metadata).forEach(([k, v]) => {
        appendMetaRow(elMetaList, k, formatFieldValue(v) || '—');
      });
    }
  }

  function isPdfSource(doc) {
    if (!doc) return false;
    if (typeof doc.is_native_pdf === 'boolean') return true; // fue tratado como PDF
    const name = String(doc.original_filename || '').toLowerCase();
    return name.endsWith('.pdf');
  }

  function detectKind(doc) {
    if (!doc) return 'unknown';
    const meta = doc.metadata && typeof doc.metadata === 'object' ? doc.metadata : {};
    const ext = String(meta.source_extension || '').toLowerCase();
    if (ext === '.pdf' || isPdfSource(doc)) return 'pdf';
    if (ext === '.xml' || (doc.original_filename || '').toLowerCase().endsWith('.xml')) return 'xml';
    if (['.jpg', '.jpeg', '.png'].includes(ext)) return 'image';
    const name = String(doc.original_filename || '').toLowerCase();
    if (name.match(/\.(jpe?g|png)$/)) return 'image';
    return 'unknown';
  }

  function renderOriginal(doc) {
    clearChildren(elOriginalContainer);
    elOriginalLink.classList.add('d-none');
    elOriginalLink.removeAttribute('href');
    if (!doc || !doc.id) {
      const empty = elOriginalEmpty.cloneNode(true);
      empty.classList.remove('d-none');
      elOriginalContainer.appendChild(empty);
      return;
    }
    const kind = detectKind(doc);
    const url = window.OCR_API.originalUrl(doc.id);
    elOriginalLink.href = url;
    elOriginalLink.classList.remove('d-none');

    if (kind === 'pdf') {
      const obj = document.createElement('iframe');
      obj.src = url;
      obj.title = 'Documento original';
      obj.style.width = '100%';
      obj.style.height = '100%';
      obj.style.border = '0';
      elOriginalContainer.appendChild(obj);
      return;
    }
    if (kind === 'image') {
      const wrap = document.createElement('div');
      wrap.className = 'text-center p-2';
      const img = document.createElement('img');
      img.src = url;
      img.alt = 'Documento original';
      img.className = 'img-fluid';
      img.style.maxWidth = '100%';
      wrap.appendChild(img);
      elOriginalContainer.appendChild(wrap);
      return;
    }
    if (kind === 'xml') {
      const pre = document.createElement('pre');
      pre.className = 'small p-3 m-0';
      pre.textContent = 'Cargando XML...';
      elOriginalContainer.appendChild(pre);
      fetch(url)
        .then((r) => r.ok ? r.text() : Promise.reject(new Error('No se pudo cargar')))
        .then((text) => { pre.textContent = text; })
        .catch((err) => { pre.textContent = err.message || 'Error al cargar XML.'; });
      return;
    }
    const empty = elOriginalEmpty.cloneNode(true);
    empty.classList.remove('d-none');
    empty.textContent = 'Vista previa no disponible para este tipo de archivo.';
    elOriginalContainer.appendChild(empty);
  }

  function renderLayout(doc) {
    clearChildren(elLayoutContainer);
    elLayoutLink.classList.add('d-none');
    elLayoutLink.removeAttribute('href');
    if (!doc || !doc.id) {
      const empty = elLayoutEmpty.cloneNode(true);
      empty.classList.remove('d-none');
      elLayoutContainer.appendChild(empty);
      return;
    }
    const url = window.OCR_API.layoutUrl(doc.id);
    elLayoutLink.href = url;
    elLayoutLink.classList.remove('d-none');
    const frame = document.createElement('iframe');
    frame.src = url;
    frame.title = 'Reconstruccion con layout';
    frame.style.width = '100%';
    frame.style.height = '100%';
    frame.style.border = '0';
    frame.addEventListener('error', () => {
      const empty = elLayoutEmpty.cloneNode(true);
      empty.textContent = 'Reconstruccion no disponible.';
      empty.classList.remove('d-none');
      clearChildren(elLayoutContainer);
      elLayoutContainer.appendChild(empty);
    });
    elLayoutContainer.appendChild(frame);
  }

  function render(doc) {
    state.doc = doc || {};
    renderText(state.doc.text_content);
    renderFields(state.doc.extracted_fields);
    renderMeta(state.doc);
    renderOriginal(state.doc);
    renderLayout(state.doc);

    // Habilitar/deshabilitar boton PDF buscable.
    elExportPdf.disabled = !isPdfSource(state.doc);
    elExportPdf.title = elExportPdf.disabled
      ? 'Solo disponible para PDFs originales'
      : 'Descargar PDF buscable';

    elCard.classList.remove('d-none');
    // Scroll al resultado.
    elCard.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  function hide() {
    state.doc = null;
    elCard.classList.add('d-none');
  }

  // -------- Eventos --------

  async function onCopy() {
    const text = elTextArea.value || '';
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(text);
      } else {
        elTextArea.select();
        document.execCommand('copy');
      }
      const original = elCopyBtn.innerHTML;
      elCopyBtn.innerHTML = '<i class="bi bi-check2 me-1" aria-hidden="true"></i>Copiado';
      elCopyBtn.classList.add('btn-success');
      elCopyBtn.classList.remove('btn-outline-secondary');
      setTimeout(() => {
        elCopyBtn.innerHTML = original;
        elCopyBtn.classList.remove('btn-success');
        elCopyBtn.classList.add('btn-outline-secondary');
      }, 1500);
    } catch {
      window.OCR_APP.showAlert('No se pudo copiar al portapapeles.');
    }
  }

  function onExport(ev) {
    const btn = ev.currentTarget;
    const format = btn.getAttribute('data-format');
    if (!state.doc || !state.doc.id || !format) return;
    const url = window.OCR_API.exportUrl(state.doc.id, format);
    // Abrir en la misma pestana dispara la descarga (Content-Disposition).
    window.location.href = url;
  }

  function onProcessAnother() {
    window.OCR_UPLOAD.resetForm();
    window.OCR_APP.switchTab('process');
    document.getElementById('templateSelect').focus();
  }

  // -------- Init --------

  function init() {
    elCard = document.getElementById('resultCard');
    elTextArea = document.getElementById('resultTextArea');
    elCopyBtn = document.getElementById('copyTextBtn');
    elFieldsBody = document.getElementById('resultFieldsBody');
    elMetaList = document.getElementById('resultMetaList');
    elExportButtons = document.querySelectorAll('.export-btn');
    elExportPdf = document.getElementById('exportPdfBtn');
    elProcessAnother = document.getElementById('processAnotherBtn');
    elOriginalContainer = document.getElementById('resultOriginalContainer');
    elOriginalEmpty = document.getElementById('resultOriginalEmpty');
    elOriginalLink = document.getElementById('resultOriginalLink');
    elOriginalTabBtn = document.getElementById('result-original-link');
    elLayoutContainer = document.getElementById('resultLayoutContainer');
    elLayoutEmpty = document.getElementById('resultLayoutEmpty');
    elLayoutLink = document.getElementById('resultLayoutLink');

    elCopyBtn.addEventListener('click', onCopy);
    elExportButtons.forEach((b) => b.addEventListener('click', onExport));
    elProcessAnother.addEventListener('click', onProcessAnother);
  }

  window.OCR_RESULT = Object.freeze({
    init,
    render,
    hide,
    formatDate,
    formatLanguage,
    formatNativePdf,
  });
})();
