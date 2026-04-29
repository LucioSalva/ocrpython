/* ==========================================================
   polling.js - Polling de estado + manejo de password modal.
   ========================================================== */
(function () {
  'use strict';

  const { POLL_INTERVAL_MS } = window.OCR_CONFIG;

  const STATUS_LABEL = {
    queued: 'En cola',
    processing: 'Procesando',
    password_required: 'Requiere contrasena',
    done: 'Listo',
    error: 'Error',
  };

  const STATUS_BADGE_CLASS = {
    queued: 'bg-secondary',
    processing: 'bg-processing',
    password_required: 'bg-warning text-dark',
    done: 'bg-success',
    error: 'bg-danger',
  };

  const STATUS_MESSAGE = {
    queued: 'Documento en cola, esperando worker...',
    processing: 'Procesando documento. Esto puede tardar unos segundos.',
    password_required: 'El documento requiere contrasena para ser procesado.',
    done: 'Procesamiento completado.',
    error: 'Ocurrio un error al procesar el documento.',
  };

  // Estado interno del modulo.
  const state = {
    jobId: null,
    timer: null,
    status: null,
    passwordModalInstance: null,
    lastTriggerEl: null,
  };

  // DOM refs (resueltos en init).
  let elCard, elBadge, elJobId, elMessage, elError,
      elPwdModal, elPwdForm, elPwdInput, elPwdError,
      elPwdSubmit, elPwdSpinner, elPwdCancel;

  // ----------- UI helpers -----------

  function setBadge(status) {
    elBadge.className = 'badge ' + (STATUS_BADGE_CLASS[status] || 'bg-secondary');
    elBadge.textContent = STATUS_LABEL[status] || status || '-';
  }

  function setMessage(status, errorMessage) {
    elMessage.textContent = STATUS_MESSAGE[status] || '...';
    if (status === 'error' && errorMessage) {
      elError.classList.remove('d-none');
      elError.textContent = errorMessage;
    } else {
      elError.classList.add('d-none');
      elError.textContent = '';
    }
  }

  function showStatusCard(jobId, status) {
    elCard.classList.remove('d-none');
    elJobId.textContent = jobId;
    setBadge(status);
    setMessage(status);
  }

  function hideStatus() {
    stopTimer();
    elCard.classList.add('d-none');
    state.jobId = null;
    state.status = null;
  }

  function stopTimer() {
    if (state.timer) {
      clearInterval(state.timer);
      state.timer = null;
    }
  }

  // ----------- Modal password -----------

  function openPasswordModal() {
    elPwdInput.value = '';
    elPwdError.classList.add('d-none');
    elPwdError.textContent = '';
    state.lastTriggerEl = document.activeElement;
    if (!state.passwordModalInstance) {
      state.passwordModalInstance = new bootstrap.Modal(elPwdModal);
    }
    state.passwordModalInstance.show();
  }

  function closePasswordModal() {
    if (state.passwordModalInstance) {
      state.passwordModalInstance.hide();
    }
  }

  // Foco al abrir.
  function bindModalFocus() {
    elPwdModal.addEventListener('shown.bs.modal', () => {
      elPwdInput.focus();
    });
    elPwdModal.addEventListener('hidden.bs.modal', () => {
      // Devolver foco si existe el origen.
      if (state.lastTriggerEl && typeof state.lastTriggerEl.focus === 'function') {
        try { state.lastTriggerEl.focus(); } catch { /* noop */ }
      }
    });
  }

  async function onPasswordCancel() {
    // Cancelar el modal: borrar el documento del backend para que
    // no quede colgado en `password_required` para siempre.
    const id = state.jobId;
    if (!id) {
      hideStatus();
      return;
    }
    try {
      await window.OCR_API.deleteDocument(id);
    } catch (err) {
      // Si falla el delete, igual ocultamos la card y avisamos.
      window.OCR_APP.showAlert(
        err.message || 'No se pudo eliminar el documento cancelado.'
      );
    }
    hideStatus();
  }

  async function onPasswordSubmit(ev) {
    ev.preventDefault();
    if (!state.jobId) return;
    const pwd = elPwdInput.value;
    if (!pwd) {
      elPwdError.classList.remove('d-none');
      elPwdError.textContent = 'Ingresa una contrasena.';
      return;
    }
    elPwdSpinner.classList.remove('d-none');
    elPwdSubmit.disabled = true;
    elPwdError.classList.add('d-none');
    try {
      await window.OCR_API.submitPassword(state.jobId, pwd);
      closePasswordModal();
      // Reanudar polling: el backend cambia a queued/processing.
      setBadge('processing');
      setMessage('processing');
      startTimer();
    } catch (err) {
      elPwdError.classList.remove('d-none');
      elPwdError.textContent = err.message || 'Contrasena incorrecta o error.';
    } finally {
      elPwdSpinner.classList.add('d-none');
      elPwdSubmit.disabled = false;
    }
  }

  // ----------- Loop de polling -----------

  async function tick() {
    if (!state.jobId) return;
    try {
      const data = await window.OCR_API.getStatus(state.jobId);
      handleStatus(data);
    } catch (err) {
      // Errores transitorios: avisar pero seguir intentando una vez mas.
      // Si es de red duro paramos.
      if (err.isNetwork) {
        stopTimer();
        window.OCR_APP.showAlert(err.message);
        setBadge('error');
        setMessage('error', err.message);
      } else {
        // 4xx/5xx: detener si persiste.
        stopTimer();
        setBadge('error');
        setMessage('error', err.message || 'Error al consultar estado.');
      }
    }
  }

  function handleStatus(data) {
    if (!data || !data.status) return;
    state.status = data.status;
    setBadge(data.status);
    setMessage(data.status, data.error_message);

    if (data.status === 'done') {
      stopTimer();
      loadFinalDocument();
      return;
    }
    if (data.status === 'error') {
      stopTimer();
      return;
    }
    if (data.status === 'password_required') {
      stopTimer();
      openPasswordModal();
      return;
    }
    // queued | processing -> seguir
  }

  async function loadFinalDocument() {
    try {
      const detail = await window.OCR_API.getDocument(state.jobId);
      window.OCR_RESULT.render(detail);
    } catch (err) {
      window.OCR_APP.showAlert(err.message || 'No se pudo obtener el documento.');
    }
  }

  function startTimer() {
    stopTimer();
    state.timer = setInterval(tick, POLL_INTERVAL_MS);
    // Tick inmediato para evitar 1.5s de espera.
    tick();
  }

  // ----------- Public API -----------

  function start(jobId, initialStatus) {
    state.jobId = jobId;
    state.status = initialStatus || 'queued';
    showStatusCard(jobId, state.status);
    if (state.status === 'password_required') {
      openPasswordModal();
      return;
    }
    if (state.status === 'done') {
      loadFinalDocument();
      return;
    }
    if (state.status === 'error') {
      return;
    }
    startTimer();
  }

  function init() {
    elCard = document.getElementById('statusCard');
    elBadge = document.getElementById('statusBadge');
    elJobId = document.getElementById('statusJobId');
    elMessage = document.getElementById('statusMessage');
    elError = document.getElementById('statusError');

    elPwdModal = document.getElementById('passwordModal');
    elPwdForm = document.getElementById('passwordForm');
    elPwdInput = document.getElementById('pdfPasswordInput');
    elPwdError = document.getElementById('passwordError');
    elPwdSubmit = document.getElementById('passwordSubmitBtn');
    elPwdSpinner = document.getElementById('passwordSpinner');
    elPwdCancel = document.getElementById('passwordCancelBtn');

    elPwdForm.addEventListener('submit', onPasswordSubmit);
    if (elPwdCancel) {
      elPwdCancel.addEventListener('click', onPasswordCancel);
    }
    bindModalFocus();
  }

  window.OCR_POLLING = Object.freeze({
    init,
    start,
    hideStatus,
  });
})();
