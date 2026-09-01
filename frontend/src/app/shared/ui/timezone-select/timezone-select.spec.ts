import '@angular/compiler';
import { describe, expect, it, vi } from 'vitest';

import { TimezoneSelectComponent } from './timezone-select';

describe('TimezoneSelectComponent', () => {
  it('offers separate searchable IANA options and emits the exact selected zone', () => {
    const component = new TimezoneSelectComponent();
    const emitted = vi.fn();
    component.valueChange.subscribe(emitted);

    expect(component.options.some(option => option.value === 'America/Lima')).toBe(true);
    expect(component.options.some(option => option.value === 'America/Bogota')).toBe(true);
    expect(component.searchTimezone('UTC-5', component.options.find(option => option.value === 'America/Lima')!)).toBe(true);

    component.update('America/Bogota');
    expect(emitted).toHaveBeenCalledWith('America/Bogota');
  });
});
