import { describe, expect, it } from 'vitest';
import { humanizeApiError } from './api-error';

describe('humanizeApiError', () => {
  it('renders FastAPI validation arrays without object coercion', () => {
    const error = { status: 422, error: { detail: [{ loc: ['body', 'reason'], msg: 'String should have at least 5 characters' }] } };
    expect(humanizeApiError(error, 'Failed.')).toBe('Reason: String should have at least 5 characters');
  });

  it('uses a safe message for server and connectivity failures', () => {
    expect(humanizeApiError({ status: 0 }, 'Failed.')).toContain('could not be reached');
    expect(humanizeApiError({ status: 503 }, 'Failed.')).toBe('Failed. Please try again. Reference: HTTP 503.');
  });
});
