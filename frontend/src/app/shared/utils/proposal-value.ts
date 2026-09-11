type ValuePath = Array<string | number>;

interface EditableLeaf {
  path: ValuePath;
  label: string;
  value: unknown;
}

export function humanizeProposalKey(key: string): string {
  const text = key.replace(/([a-z])([A-Z])/g, '$1 $2').replaceAll('_', ' ').replaceAll('-', ' ').trim();
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : 'Value';
}

function primitiveText(value: unknown): string {
  if (value === null || value === undefined || value === '') return 'Not provided';
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  return String(value);
}

function leaves(value: unknown, path: ValuePath = [], labels: string[] = []): EditableLeaf[] {
  if (Array.isArray(value)) {
    if (!value.length || value.every(item => item === null || ['string', 'number', 'boolean'].includes(typeof item))) {
      return [{ path, label: labels.join(' › ') || 'Values', value }];
    }
    return value.flatMap((item, index) => leaves(item, [...path, index], [...labels, `Item ${index + 1}`]));
  }
  if (value && typeof value === 'object') {
    return Object.entries(value as Record<string, unknown>).flatMap(([key, item]) =>
      leaves(item, [...path, key], [...labels, humanizeProposalKey(key)]));
  }
  return [{ path, label: labels.join(' › ') || 'Value', value }];
}

function leafText(value: unknown): string {
  if (Array.isArray(value)) return value.map(primitiveText).join('; ');
  return primitiveText(value);
}

export function formatProposalValue(field: string, value: unknown): string {
  if (field === 'official_corporate_website' && value && typeof value === 'object' && !Array.isArray(value)) {
    const website = value as { exists?: boolean; url?: unknown };
    if (website.exists === false) return 'No official website';
    if (typeof website.url === 'string') return website.url;
  }
  if (Array.isArray(value) && value.every(item => item === null || ['string', 'number', 'boolean'].includes(typeof item))) {
    return value.map(primitiveText).join('\n');
  }
  if (value && typeof value === 'object') {
    return leaves(value).map(item => `${item.label}: ${leafText(item.value)}`).join('\n');
  }
  return primitiveText(value) === 'Not provided' ? '' : primitiveText(value);
}

function parsePrimitive(text: string, original: unknown): unknown {
  const value = text.trim();
  if (original === null || original === undefined) return /^(not provided|none)?$/i.test(value) ? null : value;
  if (typeof original === 'boolean') {
    if (/^(yes|true|1)$/i.test(value)) return true;
    if (/^(no|false|0)$/i.test(value)) return false;
    return original;
  }
  if (typeof original === 'number') {
    const parsed = Number(value.replaceAll(',', ''));
    return Number.isFinite(parsed) ? parsed : original;
  }
  return value;
}

function parseArray(text: string, original: unknown[]): unknown[] {
  const values = text.split(/\n|;|,/).map(item => item.trim()).filter(item => item && !/^not provided$/i.test(item));
  const template = original.find(item => item !== null && item !== undefined);
  return values.map(item => parsePrimitive(item, template));
}

function cloneValue<T>(value: T): T {
  return value === undefined ? value : JSON.parse(JSON.stringify(value)) as T;
}

function setAtPath(target: unknown, path: ValuePath, value: unknown): void {
  if (!path.length) return;
  let cursor = target as Record<string | number, unknown>;
  for (let index = 0; index < path.length - 1; index++) cursor = cursor[path[index]] as Record<string | number, unknown>;
  cursor[path[path.length - 1]] = value;
}

export function parseProposalValue(field: string, draft: string, original: unknown): unknown {
  const trimmed = draft.trim();
  if (field === 'official_corporate_website') {
    if (/^(no official website|no website|none|no)$/i.test(trimmed)) return { exists: false, url: null };
    return { exists: true, url: trimmed };
  }
  if (Array.isArray(original)) return parseArray(trimmed, original);
  if (!original || typeof original !== 'object') return parsePrimitive(trimmed, original);

  const result = cloneValue(original);
  const editableLeaves = leaves(original);
  const lines = draft.split('\n').map(line => line.trim()).filter(Boolean);
  for (const leaf of editableLeaves) {
    const prefix = `${leaf.label}:`;
    const line = lines.find(item => item.toLocaleLowerCase().startsWith(prefix.toLocaleLowerCase()));
    if (!line) continue;
    const text = line.slice(line.indexOf(':') + 1).trim();
    setAtPath(result, leaf.path, Array.isArray(leaf.value) ? parseArray(text, leaf.value) : parsePrimitive(text, leaf.value));
  }
  return result;
}

export function isStructuredProposalValue(value: unknown): boolean {
  return Array.isArray(value) || (!!value && typeof value === 'object');
}
