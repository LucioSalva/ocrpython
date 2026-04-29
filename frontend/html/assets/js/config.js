/* ==========================================================
   config.js - Configuracion global de la app.
   El navegador llama directo al backend FastAPI (no hay proxy).
   ========================================================== */
(function () {
  'use strict';

  // BASE_URL del backend FastAPI. En docker-compose el backend se publica
  // en 127.0.0.1:8000. Si cambias el puerto en .env ajusta aqui tambien.
  const BASE_URL = 'http://localhost:8000';

  // Tamano maximo permitido en cliente (debe coincidir con MAX_UPLOAD_MB).
  const MAX_UPLOAD_MB = 20;
  const MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024;

  // Tipos aceptados para validacion en cliente.
  const ACCEPTED_EXTENSIONS = ['pdf', 'jpg', 'jpeg', 'png', 'xml'];
  const ACCEPTED_MIME = [
    'application/pdf',
    'image/jpeg',
    'image/png',
    'application/xml',
    'text/xml',
  ];

  // Polling
  const POLL_INTERVAL_MS = 1500;

  // Paginacion historial
  const HISTORY_PAGE_SIZE = 20;

  // Exponer namespace global.
  window.OCR_CONFIG = Object.freeze({
    BASE_URL,
    MAX_UPLOAD_MB,
    MAX_UPLOAD_BYTES,
    ACCEPTED_EXTENSIONS,
    ACCEPTED_MIME,
    POLL_INTERVAL_MS,
    HISTORY_PAGE_SIZE,
  });
})();
