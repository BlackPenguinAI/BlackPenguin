import '@angular/compiler';
import { describe, expect, it } from 'vitest';
import { AgentComponent } from './agent';

describe('AgentComponent simulation form', () => {
  const component = () => new AgentComponent(
    {} as any,
    { markForCheck: () => undefined } as any,
    { snapshot: { queryParamMap: { get: () => null } } } as any,
  );

  it('prevents starting a simulation until every required field is complete', () => {
    const value = component();
    value.options = [{ id: 'project', campaigns: [{ id: 'campaign' }] }];
    value.projectId = 'project';
    value.campaignId = 'campaign';
    value.form.full_name = 'Taylor Morgan';
    value.form.phone = '+13055550142';
    expect(value.formComplete).toBe(false);
    value.form.consent = true;
    expect(value.formComplete).toBe(true);
  });

  it('shows only campaigns that belong to the selected Project', () => {
    const value = component();
    value.options = [
      { id: 'p1', campaigns: [{ id: 'c1' }] },
      { id: 'p2', campaigns: [{ id: 'c2' }] },
    ];
    value.projectId = 'p2';
    expect(value.campaigns.map(item => item.id)).toEqual(['c2']);
  });
});
