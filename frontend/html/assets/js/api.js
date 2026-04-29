/* ==========================================================
   api.js - Wrapper sobre fetch contra el backend FastAPI.
   Centraliza errores y manejo de "backend caido".
   ========================================================== */
(function () {
  'use strict';

  const { BASE_URL } = window.OCR_CONFIG;

  /**
   * Error de red estructurado.
   */
  class ApiError extends Error {
    constructor(message, { status = 0, data = null, isNetwork = false } = {}) {
      super(message);
      this.name = 'ApiError';
      this.status = status;
      this.data = data;
      this.isNetwork = isNetwork;
    }
  }

  /**
   * Construye URL absoluta al backend.
   */
  function url(path, params) {
    const u = new URL(path.replace(/^\//, ''), BASE_URL.replace(/\/?$/, '/'));
    if (params) {
      Object.entries(params).forEach(([k, v]) => {
        if (v === undefined || v === null || v === '') return;
        u.searchParams.set(k, String(v));
      });
    }
    return u.toString();
  }

  /**
   * Wrapper de fetch -> JSON con manejo unificado de errores.
   */
  async function request(method, path, { params, json, signal } = {}) {
    const init = {
      method,
      headers: { Accept: 'application/json' },
      signal,
    };
    if (json !== undefined) {
      init.headers['Content-Type'] = 'application/json';
      init.body = JSON.stringify(json);
    }

    let response;
    try {
      response = await fetch(url(path, params), init);
    } catch (err) {
      throw new ApiError(
        'No se pudo conectar con el backend (localhost:8000). Esta el contenedor corriendo?',
        { isNetwork: true }
      );
    }

    let data = null;
    const ct = response.headers.get('content-type') || '';
    if (ct.includes('application/json')) {
      try { data = await response.json(); } catch { data = null; }
    } else {
      try { data = await response.text(); } catch { data = null; }
    }

    if (!response.ok) {
      const detail = (data && typeof data === 'object' && data.detail) || response.statusText;
      throw new ApiError(
        typeof detail === 'string' ? detail : 'Error del backend',
        { status: response.status, data }
      );
    }
    return data;
  }

  // -------------- Endpoints concretos --------------

  function listTemplates() {
    return request('GET', '/templates');
  }

  function getStatus(id) {
    return request('GET', `/documents/${encodeURIComponent(id)}/status`);
  }

  function getDocument(id) {
    return request('GET', `/documents/${encodeURIComponent(id)}`);
  }

  function submitPassword(id, password) {
    return request('POST', `/documents/${encodeURIComponent(id)}/password`, {
      json: { password },
    });
  }

  function listDocuments({ q = '', template = '', limit = 20, offset = 0 } = {}) {
    return request('GET', '/documents', {
      params: { q, template, limit, offset },
    });
  }

  function deleteDocument(id) {
    return request('DELETE', `/documents/${encodeURIComponent(id)}`);
  }

  /**
   * Subida con XMLHttpRequest para tener evento `progress` real.
   * @returns {Promise<{id: string, status: string}>}
   */
  function uploadDocument({ file, templateCode, password, onProgress, onAbort }) {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open('POST', url('/documents'), true);

      xhr.upload.addEventListener('progress', (ev) => {
        if (ev.lengthComputable && typeof onProgress === 'function') {
          onProgress(Math.round((ev.loaded / ev.total) * 100));
        }
      });

      xhr.addEventListener('load', () => {
        let parsed = null;
        try { parsed = JSON.parse(xhr.responseText || 'null'); } catch { parsed = null; }
        if (xhr.status >= 200 && xhr.status < 300) {
          resolve(parsed || {});
        } else {
          const msg = (parsed && parsed.detail) || `Error ${xhr.status}`;
          reject(new ApiError(typeof msg === 'string' ? msg : 'Error al subir', {
            status: xhr.status, data: parsed,
          }));
        }
      });

      xhr.addEventListener('error', () => {
        reject(new ApiError(
          'No se pudo conectar con el backend (localhost:8000). Esta el contenedor corriendo?',
          { isNetwork: true }
        ));
      });

      xhr.addEventListener('abort', () => {
        if (typeof onAbort === 'function') onAbort();
        reject(new ApiError('Subida cancelada', { status: 0 }));
      });

      const fd = new FormData();
      fd.append('file', file);
      fd.append('template_code', templateCode);
      if (password) fd.append('password', password);
      xhr.send(fd);

      // Permite cancelar desde fuera adjuntando metodo.
      // (No usado en UI actual pero util a futuro.)
      uploadDocument._lastXhr = xhr;
    });
  }

  /**
   * URL absoluta para descargar un export en una pestana nueva.
   */
  function exportUrl(id, format) {
    return url(`/documents/${encodeURIComponent(id)}/export`, { format });
  }

  /**
   * URL absoluta para servir el archivo original inline (preview).
   */
  function originalUrl(id) {
    return url(`/documents/${encodeURIComponent(id)}/original`);
  }

  /**
   * URL absoluta para el HTML reconstruido con layout preservado.
   */
  function layoutUrl(id) {
    return url(`/documents/${encodeURIComponent(id)}/layout`);
  }

  window.OCR_API = Object.freeze({
    ApiError,
    listTemplates,
    getStatus,
    getDocument,
    submitPassword,
    listDocuments,
    deleteDocument,
    uploadDocument,
    exportUrl,
    originalUrl,
    layoutUrl,
  });
})();
