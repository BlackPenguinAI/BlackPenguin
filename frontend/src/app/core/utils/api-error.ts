interface ValidationDetail {
  loc?: Array<string | number>;
  msg?: string;
  message?: string;
}

function readableField(detail: ValidationDetail): string {
  const field = (detail.loc || []).filter(value => value !== 'body').at(-1);
  return typeof field === 'string'
    ? field.replaceAll('_', ' ').replace(/^./, value => value.toUpperCase())
    : '';
}

function detailMessage(detail: unknown): string | null {
  if (typeof detail === 'string' && detail.trim()) return detail.trim();
  if (Array.isArray(detail)) {
    const messages = detail.map(detailMessage).filter((value): value is string => Boolean(value));
    return messages.length ? messages.join(' ') : null;
  }
  if (!detail || typeof detail !== 'object') return null;
  const value = detail as ValidationDetail & { detail?: unknown; error?: unknown };
  if (typeof value.message === 'string' && value.message.trim()) return value.message.trim();
  if (typeof value.msg === 'string' && value.msg.trim()) {
    const field = readableField(value);
    return field ? `${field}: ${value.msg.trim()}` : value.msg.trim();
  }
  return detailMessage(value.detail) || detailMessage(value.error);
}

/** Convert FastAPI/Pydantic and network failures into user-facing text. */
export function humanizeApiError(error: unknown, fallback: string): string {
  const candidate = error as { status?: number; statusText?: string; error?: unknown; message?: string } | null;
  const message = detailMessage(candidate?.error) || detailMessage(error);
  if (message && message !== '[object Object]') return message;
  if (candidate?.status === 0) return 'The server could not be reached. Check your connection and try again.';
  if (candidate?.status === 401) return 'Your session has expired. Sign in again and retry.';
  if (candidate?.status === 403) return 'You do not have permission to perform this action.';
  if (candidate?.status === 404) return 'The requested record no longer exists.';
  if (candidate?.status === 409) return 'This action conflicts with the current record state. Refresh and try again.';
  if (candidate?.status && candidate.status >= 500) return `${fallback} Please try again. Reference: HTTP ${candidate.status}.`;
  return fallback;
}
