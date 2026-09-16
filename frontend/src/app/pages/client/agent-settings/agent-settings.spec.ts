import '@angular/compiler';
import { of } from 'rxjs';
import { describe, expect, it, vi } from 'vitest';
import { AgentSettingsComponent } from './agent-settings';

describe('AgentSettingsComponent', () => {
  function setup() {
    const http = {
      get: vi.fn().mockReturnValue(of([])),
      put: vi.fn().mockReturnValue(of({})),
      post: vi.fn().mockReturnValue(of({})),
      delete: vi.fn().mockReturnValue(of({})),
    } as any;
    const cdr = { markForCheck: vi.fn() } as any;
    return { component: new AgentSettingsComponent(http, cdr), http };
  }

  it('creates and edits a weekday contact window without mutating other days', () => {
    const { component } = setup();
    component.toggleDay(0);
    component.toggleDay(1);
    component.setTime(0, 'start', '10:30');
    expect(component.policy.weekly_windows['0']).toEqual([{ start: '10:30', end: '18:00' }]);
    expect(component.policy.weekly_windows['1']).toEqual([{ start: '09:00', end: '18:00' }]);
  });

  it('normalizes blackout dates before saving the operating policy', () => {
    const { component, http } = setup();
    component.blackoutText = '2026-12-25, 2027-01-01 ';
    component.savePolicy();
    expect(http.put).toHaveBeenCalledWith(
      expect.stringContaining('/governance/operating-policy'),
      expect.objectContaining({ blackout_dates: ['2026-12-25', '2027-01-01'], project_id: null }),
    );
  });
});
