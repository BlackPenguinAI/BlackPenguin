import '@angular/compiler';
import { of } from 'rxjs';
import { describe, expect, it } from 'vitest';
import { AgentComponent } from './agent';

describe('AgentComponent simulation form', () => {
  const component = (http: any = {}) =>
    new AgentComponent(
      http,
      { markForCheck: () => undefined } as any,
      { snapshot: { queryParamMap: { get: () => null } } } as any,
    );

  it('prevents starting a simulation until every required field is complete', () => {
    const value = component();
    value.options = [
      { id: 'project', campaigns: [{ id: 'campaign' }], products: [{ id: 'property_type:home' }] },
    ];
    value.projectId = 'project';
    value.campaignId = 'campaign';
    value.form.first_name = 'Taylor';
    value.form.last_name = 'Morgan';
    value.form.phone = '+13055550142';
    value.form.email = 'taylor@example.com';
    value.form.product_id = 'property_type:home';
    value.form.budget_min = 600000;
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
    expect(value.campaigns.map((item) => item.id)).toEqual(['c2']);
  });

  it('shows only products from the selected Project and validates the budget range', () => {
    const value = component();
    value.options = [
      { id: 'p1', campaigns: [], products: [{ id: 'property_type:a' }] },
      { id: 'p2', campaigns: [], products: [{ id: 'property_type:b' }] },
    ];
    value.projectId = 'p2';
    value.form.product_id = 'property_type:b';
    value.form.budget_min = 700000;
    value.form.budget_max = 600000;
    expect(value.products.map((item) => item.id)).toEqual(['property_type:b']);
    expect(value.budgetValid).toBe(false);
    value.form.budget_max = 800000;
    expect(value.budgetValid).toBe(true);
  });

  it('saves the lead before requesting the initial SMS and always clears loading state', () => {
    const calls: string[] = [];
    const conversation = {
      id: 'conversation',
      lead_id: 'lead',
      simulation_id: 'simulation',
      simulation_status: 'initializing',
      is_paused: false,
      appointment_id: null,
    };
    const http = {
      post: (url: string) => {
        calls.push(url);
        return url.endsWith('/simulations')
          ? of({ simulation_id: 'simulation', conversation_id: 'conversation' })
          : of({ reply: 'Hello' });
      },
      get: (url: string) => {
        if (url.includes('/messages')) return of([]);
        if (url.includes('/slots')) return of([]);
        return of([conversation]);
      },
    };
    const value = component(http);
    value.options = [
      { id: 'project', campaigns: [{ id: 'campaign' }], products: [{ id: 'property_type:home' }] },
    ];
    value.projectId = 'project';
    value.campaignId = 'campaign';
    value.form = {
      first_name: 'Taylor',
      last_name: 'Morgan',
      phone: '+13055550142',
      email: 'taylor@example.com',
      product_id: 'property_type:home',
      budget_min: 600000,
      budget_max: 750000,
      consent: true,
    };
    value.startSimulation();
    expect(calls[0].endsWith('/sales-agent/simulations')).toBe(true);
    expect(calls[1].endsWith('/sales-agent/simulations/simulation/initial-message')).toBe(true);
    expect(value.creating).toBe(false);
    expect(value.generatingInitial).toBe(false);
  });
});
