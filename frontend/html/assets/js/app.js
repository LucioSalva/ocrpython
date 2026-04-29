/* ==========================================================
   app.js - Bootstrapping y orquestacion entre modulos.
   ========================================================== */
(function () {
  'use strict';

  // -------- Alertas globales (errores de red, etc) --------

  let alertEl;

  function showAlert(message, kind = 'danger') {
    if (!alertEl) return;
    alertEl.className = `alert alert-${kind}`;
    alertEl.textContent = message || 'Ocurrio un error.';
    alertEl.classList.remove('d-none');
    // Auto-hide despues de 8s para info/success.
    if (kind !== 'danger') {
      setTimeout(clearAlert, 8000);
    }
  }

  function clearAlert() {
    if (!alertEl) return;
    alertEl.classList.add('d-none');
    alertEl.textContent = '';
  }

  // -------- Cambio de tab programatico --------

  function switchTab(name) {
    const id = name === 'history' ? 'tab-history-link' : 'tab-process-link';
    const trigger = document.getElementById(id);
    if (!trigger) return;
    const tab = bootstrap.Tab.getOrCreateInstance(trigger);
    tab.show();
  }

  // -------- Init --------

  function init() {
    alertEl = document.getElementById('globalAlert');

    // Exponer helpers globales antes de inicializar modulos que los usan.
    window.OCR_APP = Object.freeze({
      showAlert,
      clearAlert,
      switchTab,
    });

    // Inicializacion de modulos.
    window.OCR_POLLING.init();
    window.OCR_RESULT.init();
    window.OCR_HISTORY.init();
    window.OCR_UPLOAD.init();

    // Lazy-load del historial al activar su tab.
    const histLink = document.getElementById('tab-history-link');
    if (histLink) {
      histLink.addEventListener('shown.bs.tab', () => {
        window.OCR_HISTORY.ensureLoaded();
      });
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
