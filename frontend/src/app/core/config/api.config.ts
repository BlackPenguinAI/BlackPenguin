import { isDevMode } from '@angular/core';

/**
 * Single API root for browser clients.
 *
 * Production deliberately uses a same-origin relative URL. This keeps the
 * browser on HTTPS, works on non-production hostnames, and lets Nginx proxy
 * /api requests without hard-coding a public domain in every feature.
 */
export const API_V1_URL = isDevMode()
  ? 'http://localhost:8000/api/v1'
  : '/api/v1';
