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
