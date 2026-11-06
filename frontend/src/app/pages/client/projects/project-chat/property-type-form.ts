import { ProjectPropertyType } from './project-onboarding.models';

// One field contract for manual, extracted and existing property types.
export interface PropertyTypeField {
  key: keyof ProjectPropertyType;
  label: string;
  kind: 'text' | 'number' | 'textarea' | 'currency' | 'area_unit';
  required?: boolean;
  conditional?: boolean;
  step?: number | string;
}
export const PROPERTY_TYPE_FIELDS: readonly PropertyTypeField[] = [
  { key: 'name', label: 'Name', kind: 'text', required: true },
  { key: 'code', label: 'Code', kind: 'text' },
  { key: 'description', label: 'Description', kind: 'textarea' },
  { key: 'bedrooms', label: 'Bedrooms', kind: 'text' },
  { key: 'bathrooms', label: 'Bathrooms', kind: 'number', step: 0.5 },
  { key: 'area_min', label: 'Area minimum', kind: 'number', step: 'any' },
  { key: 'area_max', label: 'Area maximum', kind: 'number', step: 'any' },
  { key: 'area_unit', label: 'Area unit', kind: 'area_unit', conditional: true },
  { key: 'total_units', label: 'Total units', kind: 'number', step: 1 },
  { key: 'available_units', label: 'Available units', kind: 'number', step: 1 },
  { key: 'starting_price', label: 'Starting price', kind: 'number', step: 'any' },
  { key: 'maximum_price', label: 'Maximum price', kind: 'number', step: 'any' },
  { key: 'currency', label: 'Currency', kind: 'currency', conditional: true },
  { key: 'features', label: 'Features (one per line)', kind: 'textarea' },
];

const EDITABLE_KEYS = [...PROPERTY_TYPE_FIELDS.map(field => field.key), 'source_reference', 'sort_order'] as const;

export function propertyTypeDetails(value: Partial<ProjectPropertyType>): Record<string, unknown> {
  return JSON.parse(JSON.stringify(Object.fromEntries(EDITABLE_KEYS.map(key => [key, value[key] ?? null]))));
}

/** Deferral timestamps are server UTC, including legacy naive ISO strings. */
export function propertyDraftTimestamp(value: unknown): number {
  if(typeof value!=='string') return 0;
  const utc=/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?$/.test(value) ? value+'Z' : value;
  const parsed=Date.parse(utc);
  const fraction=value.match(/\.(\d+)(?:Z|[+-]\d{2}:?\d{2})?$/)?.[1] || '';
  return Number.isFinite(parsed) ? parsed+(Number('0.'+fraction)*1000)%1 : 0;
}

export function restorePropertyTypeDraft(server: ProjectPropertyType, draft: any, record: any): boolean {
  if (!draft || record?.completed_at) return false;
  if (draft.details_base && typeof draft.details_base === 'object') {
    // Image changes do not alter this scalar baseline. A real scalar change
    // must not be silently overwritten by an old saved draft.
    const current = propertyTypeDetails(server);
    return Object.keys(current).every(key => JSON.stringify(current[key]) === JSON.stringify(draft.details_base[key] ?? null));
  }
  // Legacy active drafts predate scalar baselines: keep their explicit pending
  // review rather than treating an image-only timestamp as a scalar save.
  return !!(record?.resumed || record?.deferred)
    || !server.updated_at || !record?.updated_at
    || Date.parse(server.updated_at) <= Date.parse(record.updated_at);
}

/** Keep pending scalar edits; media and server-owned metadata stay authoritative. */
export function mergePropertyTypeDraft(
  server: ProjectPropertyType, local: Partial<ProjectPropertyType>, submitted?: Partial<ProjectPropertyType>,
): ProjectPropertyType {
  const result = { ...server };
  for (const key of EDITABLE_KEYS) {
    if (Object.prototype.hasOwnProperty.call(local, key)
        && (!submitted || JSON.stringify(local[key]) !== JSON.stringify(submitted[key]))) {
      (result as any)[key] = local[key];
    }
  }
  return result;
}

export function propertyTypeSnapshot(value: Partial<ProjectPropertyType>): Partial<ProjectPropertyType> {
  return JSON.parse(JSON.stringify(value));
}
