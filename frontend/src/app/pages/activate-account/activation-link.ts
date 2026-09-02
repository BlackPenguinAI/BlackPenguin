export interface ActivationLinkParameters {
  state: string;
  oobCode: string;
  source: 'direct' | 'nested' | 'fragment' | 'missing';
}

type ParameterReader = (key: string) => string | null;

function parseCandidate(value: string, source: ActivationLinkParameters['source'], depth = 0): ActivationLinkParameters {
  if (!value || depth > 3) return { state: '', oobCode: '', source: 'missing' };
  try {
    const url = new URL(value, 'https://blackpenguin.ai');
    let state = url.searchParams.get('state') || '';
    let oobCode = url.searchParams.get('oobCode') || '';
    if (state && oobCode) return { state, oobCode, source };
    for (const key of ['continueUrl', 'link']) {
      const nested = url.searchParams.get(key);
      if (nested) {
        const result = parseCandidate(nested, 'nested', depth + 1);
        state ||= result.state;
        oobCode ||= result.oobCode;
        if (state && oobCode) return { state, oobCode, source: 'nested' };
      }
    }
    if (url.hash.length > 1) {
      const fragment = parseCandidate(`/?${url.hash.slice(1).replace(/^\?/, '')}`, 'fragment', depth + 1);
      state ||= fragment.state;
      oobCode ||= fragment.oobCode;
      if (state && oobCode) return { state, oobCode, source: 'fragment' };
    }
    return { state, oobCode, source };
  } catch {
    return { state: '', oobCode: '', source: 'missing' };
  }
}

export function activationLinkParameters(read: ParameterReader, fragment = ''): ActivationLinkParameters {
  let state = read('state') || '';
  let oobCode = read('oobCode') || '';
  if (state && oobCode) return { state, oobCode, source: 'direct' };

  for (const key of ['continueUrl', 'link']) {
    const candidate = read(key);
    if (candidate) {
      const result = parseCandidate(candidate, 'nested');
      state ||= result.state;
      oobCode ||= result.oobCode;
      if (state && oobCode) return { state, oobCode, source: 'nested' };
    }
  }

  if (fragment) {
    const result = parseCandidate(`/?${fragment.replace(/^\?/, '')}`, 'fragment');
    state ||= result.state;
    oobCode ||= result.oobCode;
    if (state && oobCode) return { state, oobCode, source: 'fragment' };
  }
  return { state, oobCode, source: state || oobCode ? 'direct' : 'missing' };
}
