/* ==========================================================
   upload.js - Logica de subida + drag&drop + barra de progreso.
   ========================================================== */
(function () {
  'use strict';

  const { ACCEPTED_EXTENSIONS, MAX_UPLOAD_BYTES, MAX_UPLOAD_MB } = window.OCR_CONFIG;

  // ----------- Helpers -----------

  function getExtension(filename) {
    const m = String(filename || '').toLowerCase().match(/\.([a-z0-9]+)$/);
    return m ? m[1] : '';
  }

  function humanSize(bytes) {
    if (!Number.isFinite(bytes)) return '-';
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
  }

  function escapeHtml(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function isAccepted(file) {
    if (!file) return false;
    const ext = getExtension(file.name);
    return ACCEPTED_EXTENSIONS.includes(ext);
  }

  // ----------- Estado interno -----------

  const state = {
    file: null,
    template: '',
  };

  // ----------- DOM refs (resueltos en init) -----------

  let elTemplate, elFile, elDrop, elFileMeta, elSubmit, elSubmitSpinner,
      elProgressWrap, elProgress, elReset, elForm;

  function refreshSubmitState() {
    const enabled = !!state.file && !!state.template;
    elSubmit.disabled = !enabled;
  }

  function setFile(file) {
    if (!file) {
      state.file = null;
      elFileMeta.classList.add('d-none');
      elFileMeta.textContent = '';
      elDrop.classList.remove('has-file');
      refreshSubmitState();
      return;
    }
    if (!isAccepted(file)) {
      window.OCR_APP.showAlert(
        `Tipo de archivo no permitido. Solo: ${ACCEPTED_EXTENSIONS.join(', ').toUpperCase()}.`
      );
      return;
    }
    if (file.size > MAX_UPLOAD_BYTES) {
      window.OCR_APP.showAlert(
        `El archivo supera ${MAX_UPLOAD_MB} MB (pesa ${humanSize(file.size)}).`
      );
      return;
    }
    state.file = file;
    const safeName = escapeHtml(file.name);
    elFileMeta.classList.remove('d-none');
    elFileMeta.innerHTML =
      `<i class="bi bi-file-earmark-check text-success me-1" aria-hidden="true"></i>` +
      `<span class="text-truncate-name" title="${safeName}">${safeName}</span>` +
      ` <span class="text-muted">- ${humanSize(file.size)}</span>`;
    elDrop.classList.add('has-file');
    refreshSubmitState();
  }

  // ----------- Plantillas -----------

  async function loadTemplates() {
    elTemplate.innerHTML = '<option value="" selected disabled>Cargando plantillas...</option>';
    try {
      const items = await window.OCR_API.listTemplates();
      const list = Array.isArray(items) ? items : (items && items.items) || [];
      if (!list.length) {
        elTemplate.innerHTML = '<option value="" disabled selected>Sin plantillas</option>';
        return;
      }
      const frag = document.createDocumentFragment();
      const placeholder = document.createElement('option');
      placeholder.value = '';
      placeholder.textContent = 'Selecciona una plantilla...';
      placeholder.disabled = true;
      placeholder.selected = true;
      frag.appendChild(placeholder);

      // Tambien poblamos el filtro de historial.
      const histSel = document.getElementById('historyTemplate');
      if (histSel) {
        histSel.innerHTML = '';
        const all = document.createElement('option');
        all.value = '';
        all.textContent = 'Todas';
        histSel.appendChild(all);
      }

      list.forEach((tpl) => {
        const opt = document.createElement('option');
        opt.value = tpl.code || tpl.id || '';
        opt.textContent = tpl.name || tpl.label || tpl.code || '(sin nombre)';
        frag.appendChild(opt);
        if (histSel) {
          const o2 = document.createElement('option');
          o2.value = opt.value;
          o2.textContent = opt.textContent;
          histSel.appendChild(o2);
        }
      });
      elTemplate.innerHTML = '';
      elTemplate.appendChild(frag);
    } catch (err) {
      window.OCR_APP.showAlert(err.message || 'No se pudieron cargar plantillas.');
      elTemplate.innerHTML = '<option value="" disabled selected>Error al cargar</option>';
    }
  }

  // ----------- Eventos -----------

  function bindDragDrop() {
    elDrop.addEventListener('click', () => elFile.click());
    elDrop.addEventListener('keydown', (ev) => {
      if (ev.key === 'Enter' || ev.key === ' ') {
        ev.preventDefault();
        elFile.click();
      }
    });

    ['dragenter', 'dragover'].forEach((evt) => {
      elDrop.addEventListener(evt, (ev) => {
        ev.preventDefault();
        ev.stopPropagation();
        elDrop.classList.add('is-dragover');
      });
    });
    ['dragleave', 'drop'].forEach((evt) => {
      elDrop.addEventListener(evt, (ev) => {
        ev.preventDefault();
        ev.stopPropagation();
        elDrop.classList.remove('is-dragover');
      });
    });
    elDrop.addEventListener('drop', (ev) => {
      const dt = ev.dataTransfer;
      if (dt && dt.files && dt.files.length) {
        setFile(dt.files[0]);
      }
    });

    elFile.addEventListener('change', () => {
      setFile(elFile.files && elFile.files[0]);
    });
  }

  function bindForm() {
    elTemplate.addEventListener('change', () => {
      state.template = elTemplate.value || '';
      refreshSubmitState();
    });

    elReset.addEventListener('click', () => {
      resetForm();
    });

    elForm.addEventListener('submit', async (ev) => {
      ev.preventDefault();
      if (!state.file || !state.template) return;
      await doUpload();
    });
  }

  function resetForm() {
    state.file = null;
    state.template = '';
    elFile.value = '';
    elTemplate.value = '';
    elFileMeta.classList.add('d-none');
    elFileMeta.textContent = '';
    elDrop.classList.remove('has-file');
    elProgressWrap.classList.add('d-none');
    elProgress.style.width = '0%';
    elProgress.setAttribute('aria-valuenow', '0');
    elSubmit.disabled = true;
    elSubmitSpinner.classList.add('d-none');
    window.OCR_RESULT.hide();
    window.OCR_POLLING.hideStatus();
    window.OCR_APP.clearAlert();
  }

  // ----------- Subida -----------

  async function doUpload() {
    elSubmit.disabled = true;
    elSubmitSpinner.classList.remove('d-none');
    elProgressWrap.classList.remove('d-none');
    elProgress.style.width = '0%';
    elProgress.setAttribute('aria-valuenow', '0');
    window.OCR_APP.clearAlert();
    window.OCR_RESULT.hide();
    window.OCR_POLLING.hideStatus();

    try {
      const result = await window.OCR_API.uploadDocument({
        file: state.file,
        templateCode: state.template,
        onProgress: (pct) => {
          elProgress.style.width = `${pct}%`;
          elProgress.setAttribute('aria-valuenow', String(pct));
        },
      });
      elProgress.style.width = '100%';
      elProgress.setAttribute('aria-valuenow', '100');

      if (result && result.id) {
        window.OCR_POLLING.start(result.id, result.status || 'queued');
      } else {
        window.OCR_APP.showAlert('Respuesta inesperada del backend al subir.');
      }
    } catch (err) {
      window.OCR_APP.showAlert(err.message || 'Error al subir archivo.');
      elProgressWrap.classList.add('d-none');
    } finally {
      elSubmitSpinner.classList.add('d-none');
      refreshSubmitState();
    }
  }

  // ----------- Init -----------

  function init() {
    elTemplate = document.getElementById('templateSelect');
    elFile = document.getElementById('fileInput');
    elDrop = document.getElementById('dropZone');
    elFileMeta = document.getElementById('fileMeta');
    elSubmit = document.getElementById('submitBtn');
    elSubmitSpinner = document.getElementById('submitSpinner');
    elProgressWrap = document.getElementById('uploadProgressWrap');
    elProgress = document.getElementById('uploadProgress');
    elReset = document.getElementById('resetBtn');
    elForm = document.getElementById('uploadForm');

    bindDragDrop();
    bindForm();
    loadTemplates();
  }

  window.OCR_UPLOAD = Object.freeze({
    init,
    resetForm,
    humanSize,
    escapeHtml,
  });
})();
