import '@angular/compiler';
import { of } from 'rxjs';
import { describe, expect, it } from 'vitest';
import { LeadsComponent } from './leads';

describe('LeadsComponent', () => {
  const component = () => new LeadsComponent(
    {} as any,
    { markForCheck: () => undefined } as any,
    { navigate: () => Promise.resolve(true) } as any,
  );

  it('keeps the compatibility score and protected-trait-safe segments', () => {
    const value = component();
    expect(value.score({ intent_score: .73 })).toBe(73);
    expect(value.segments).toContain('downsizing');
    expect(value.segments).not.toContain('retirement_age');
  });

  it('adds a new Meta lead and opens its conversation without F5', () => {
    const navigations: any[] = [];
    const lead = { id: 'lead-1', project_id: 'project-1', platform: 'meta', full_name: 'Meta Lead' };
    const http = {
      get: (url: string) => url.includes('/leads/lead-1')
        ? of({ ...lead, conversation_id: 'conversation-1' })
        : of([lead]),
    };
    const component = new LeadsComponent(
      http as any,
      { markForCheck: () => undefined } as any,
      { navigate: (...args: any[]) => { navigations.push(args); return Promise.resolve(true); } } as any,
    );
    (component as any).snapshotReady = true;
    (component as any).knownLeadIds = new Set(['existing']);

    (component as any).pollLeads();

    expect(component.leads.map(item => item.id)).toEqual(['lead-1']);
    expect(component.selected.conversation_id).toBe('conversation-1');
    expect(navigations[0][0]).toEqual(['/app/agent']);
    expect(navigations[0][1].queryParams).toEqual({ project: 'project-1', lead: 'lead-1' });
  });
});
