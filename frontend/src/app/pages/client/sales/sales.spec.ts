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
      'in_progress', 'completed', 'completed_sale_pending', 'sale_closed',
    ]);
  });

  it('supports month, week and day calendar ranges', () => {
    vi.stubGlobal('localStorage', { getItem: () => 'sales' });
    const http = { get: () => ({ subscribe: () => undefined }) };
    const component = new SalesComponent(http as any, { markForCheck: () => undefined } as any);
    component.view = 'month'; expect(component.days).toHaveLength(42);
    component.view = 'week'; expect(component.days).toHaveLength(7);
    component.view = 'day'; expect(component.days).toHaveLength(1);
  });

  it('renders timezone choices with a UTC offset and standard name', () => {
    vi.stubGlobal('localStorage', { getItem: () => 'sales' });
    const component = new SalesComponent({} as any, { markForCheck: () => undefined } as any);
    expect(component.timezoneLabel('America/Lima')).toContain('UTC-05:00');
    expect(component.timezoneLabel('America/Lima')).toContain('Peru Standard Time');
  });
});
