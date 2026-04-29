/* ==========================================================
   history.js - Tab Historial: busqueda FTS + paginacion.
   ========================================================== */
(function () {
  'use strict';

  const { HISTORY_PAGE_SIZE } = window.OCR_CONFIG;

  // -------- Estado paginacion --------
  const state = {
    q: '',
    template: '',
    offset: 0,
    total: null,
    items: [],
    loaded: false,
  };

  // -------- DOM refs --------
  let elForm, elQuery, elTemplate, elBody, elPrev, elNext, elRange;

  // -------- Helpers de formato --------

  function escapeHtml(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  /**
   * Sanitiza el snippet del backend permitiendo SOLO la etiqueta <b>.
   * Cualquier otro tag se escapa. Esto evita XSS via metadata o texto arbitrario.
   */
  function sanitizeSnippet(snippet) {
    if (!snippet) return '';
    const escaped = escapeHtml(snippet);
    // Re-permitir solo <b> y </b>.
    return escaped
      .replace(/&lt;b&gt;/g, '<b>')
      .replace(/&lt;\/b&gt;/g, '</b>');
  }

  function truncateFilename(name, max = 40) {
    if (!name) return '';
    if (name.length <= max) return name;
    const ext = (name.match(/\.[a-z0-9]+$/i) || [''])[0];
    const base = name.slice(0, max - ext.length - 3);
    return `${base}...${ext}`;
  }

  // -------- Render --------

  function clear(el) { while (el.firstChild) el.removeChild(el.firstChild); }

  function renderEmpty(message) {
    clear(elBody);
    const tr = document.createElement('tr');
    const td = document.createElement('td');
    td.colSpan = 5;
    td.className = 'text-center text-muted py-4';
    td.textContent = message;
    tr.appendChild(td);
    elBody.appendChild(tr);
  }

  function renderLoading() {
    renderEmpty('Cargando...');
  }

  function renderError(msg) {
    renderEmpty(msg || 'Error al cargar historial.');
  }

  function renderRows(items) {
    clear(elBody);
    if (!items.length) {
      renderEmpty('Sin resultados.');
      return;
    }
    const frag = document.createDocumentFragment();

    items.forEach((it) => {
      const tr = document.createElement('tr');

      // Documento (nombre + snippet)
      const tdDoc = document.createElement('td');
      const nameWrap = document.createElement('div');
      const name = it.original_filename || '(sin nombre)';
      const nameSpan = document.createElement('span');
      nameSpan.className = 'fw-semibold';
      nameSpan.title = name;
      nameSpan.textContent = truncateFilename(name, 50);
      nameWrap.appendChild(nameSpan);
      tdDoc.appendChild(nameWrap);

      if (it.snippet) {
        const sn = document.createElement('span');
        sn.className = 'history-snippet';
        // Permitido HTML solo tras sanitizar (whitelist <b>).
        sn.innerHTML = sanitizeSnippet(it.snippet);
        tdDoc.appendChild(sn);
      }
      tr.appendChild(tdDoc);

      // Plantilla
      const tdTpl = document.createElement('td');
      const tplName = (it.template && (it.template.name || it.template.code)) ||
                      it.template_code || '—';
      tdTpl.textContent = tplName;
      tr.appendChild(tdTpl);

      // Idioma
      const tdLang = document.createElement('td');
      tdLang.textContent = window.OCR_RESULT.formatLanguage(it.language);
      tr.appendChild(tdLang);

      // Fecha
      const tdDate = document.createElement('td');
      tdDate.className = 'small';
      tdDate.textContent = window.OCR_RESULT.formatDate(it.created_at || it.completed_at);
      tr.appendChild(tdDate);

      // Acciones
      const tdAct = document.createElement('td');
      tdAct.className = 'text-end';
      tdAct.appendChild(buildActions(it));
      tr.appendChild(tdAct);

      frag.appendChild(tr);
    });
    elBody.appendChild(frag);
  }

  function buildActions(item) {
    const wrap = document.createElement('div');
    wrap.className = 'btn-group btn-group-sm';

    // Ver
    const view = document.createElement('button');
    view.type = 'button';
    view.className = 'btn btn-outline-primary';
    view.innerHTML = '<i class="bi bi-eye me-1" aria-hidden="true"></i>Ver';
    view.addEventListener('click', () => onView(item.id));
    wrap.appendChild(view);

    // Dropdown descargas
    const dd = document.createElement('div');
    dd.className = 'btn-group btn-group-sm';
    dd.setAttribute('role', 'group');
    const ddBtn = document.createElement('button');
    ddBtn.type = 'button';
    ddBtn.className = 'btn btn-outline-secondary dropdown-toggle';
    ddBtn.setAttribute('data-bs-toggle', 'dropdown');
    ddBtn.setAttribute('aria-expanded', 'false');
    ddBtn.innerHTML = '<i class="bi bi-download me-1" aria-hidden="true"></i>';
    const ddMenu = document.createElement('ul');
    ddMenu.className = 'dropdown-menu dropdown-menu-end';
    [
      ['txt', 'TXT', 'bi-file-earmark-text'],
      ['json', 'JSON', 'bi-file-earmark-code'],
      ['pdf', 'PDF buscable', 'bi-file-earmark-pdf'],
      ['xlsx', 'XLSX', 'bi-file-earmark-spreadsheet'],
      ['docx', 'DOCX', 'bi-file-earmark-word'],
    ].forEach(([fmt, label, icon]) => {
      const li = document.createElement('li');
      const a = document.createElement('a');
      a.className = 'dropdown-item';
      a.href = window.OCR_API.exportUrl(item.id, fmt);
      a.innerHTML = `<i class="bi ${icon} me-2" aria-hidden="true"></i>${escapeHtml(label)}`;
      li.appendChild(a);
      ddMenu.appendChild(li);
    });
    dd.appendChild(ddBtn);
    dd.appendChild(ddMenu);
    wrap.appendChild(dd);

    return wrap;
  }

  // -------- Acciones --------

  async function onView(id) {
    try {
      const detail = await window.OCR_API.getDocument(id);
      window.OCR_APP.switchTab('process');
      window.OCR_POLLING.hideStatus();
      window.OCR_RESULT.render(detail);
    } catch (err) {
      window.OCR_APP.showAlert(err.message || 'No se pudo cargar el documento.');
    }
  }

  // -------- Carga --------

  async function load() {
    renderLoading();
    elPrev.disabled = true;
    elNext.disabled = true;
    try {
      const data = await window.OCR_API.listDocuments({
        q: state.q,
        template: state.template,
        limit: HISTORY_PAGE_SIZE,
        offset: state.offset,
      });
      const items = (data && (data.items || data.results || data.data)) || [];
      const total = (data && (data.total ?? data.count)) ?? null;

      state.items = items;
      state.total = total;
      state.loaded = true;
      renderRows(items);
      updatePagination(items.length, total);
    } catch (err) {
      renderError(err.message);
    }
  }

  function updatePagination(currentCount, total) {
    const start = currentCount ? state.offset + 1 : 0;
    const end = state.offset + currentCount;
    if (total != null) {
      elRange.textContent = currentCount
        ? `Mostrando ${start}-${end} de ${total}`
        : 'Sin resultados';
      elPrev.disabled = state.offset <= 0;
      elNext.disabled = end >= total;
    } else {
      // backend no devuelve total: heuristica por tamano de pagina.
      elRange.textContent = currentCount
        ? `Mostrando ${start}-${end}`
        : 'Sin resultados';
      elPrev.disabled = state.offset <= 0;
      elNext.disabled = currentCount < HISTORY_PAGE_SIZE;
    }
  }

  // -------- Eventos --------

  function bind() {
    elForm.addEventListener('submit', (ev) => {
      ev.preventDefault();
      state.q = (elQuery.value || '').trim();
      state.template = elTemplate.value || '';
      state.offset = 0;
      load();
    });

    elPrev.addEventListener('click', () => {
      state.offset = Math.max(0, state.offset - HISTORY_PAGE_SIZE);
      load();
    });

    elNext.addEventListener('click', () => {
      state.offset = state.offset + HISTORY_PAGE_SIZE;
      load();
    });
  }

  function ensureLoaded() {
    if (!state.loaded) load();
  }

  function refresh() {
    state.offset = 0;
    load();
  }

  function init() {
    elForm = document.getElementById('historyForm');
    elQuery = document.getElementById('historyQuery');
    elTemplate = document.getElementById('historyTemplate');
    elBody = document.getElementById('historyBody');
    elPrev = document.getElementById('historyPrev');
    elNext = document.getElementById('historyNext');
    elRange = document.getElementById('historyRange');
    bind();
  }

  window.OCR_HISTORY = Object.freeze({
    init,
    ensureLoaded,
    refresh,
  });
})();
