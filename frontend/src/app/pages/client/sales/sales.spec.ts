import '@angular/compiler';
import { describe, expect, it, vi } from 'vitest';
import { SalesComponent } from './sales';

describe('SalesComponent scheduling view', () => {
  it('keeps simulated appointments in the same calendar collection', () => {
    vi.stubGlobal('localStorage', { getItem: () => 'sales' });
    const component = new SalesComponent({} as any, { markForCheck: () => undefined } as any);
    const now = new Date();
    component.meetings = [{ meeting_time: now.toISOString(), is_demo: true, status: 'confirmed' }];
    expect(component.meetingsFor(now)).toHaveLength(1);
    expect(component.count('confirmed')).toBe(1);
  });

  it('offers an IANA timezone list instead of accepting an arbitrary timezone', () => {
    vi.stubGlobal('localStorage', { getItem: () => 'sales' });
    const component = new SalesComponent({} as any, { markForCheck: () => undefined } as any);
    expect(component.timezones).toContain('UTC');
    expect(component.timezones).toContain('America/Lima');
    expect(component.timezones.length).toBeGreaterThan(10);
  });

  it('exposes only valid next steps for an active visit', () => {
    vi.stubGlobal('localStorage', { getItem: () => 'sales' });
    const component = new SalesComponent({} as any, { markForCheck: () => undefined } as any);
    expect(component.statusOptions('in_progress').map(item => item.value)).toEqual([
      'in_progress', 'completed_sale_pending', 'sale_closed',
    ]);
  });
});
