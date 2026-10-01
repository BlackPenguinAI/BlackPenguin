import '@angular/compiler';
import { of, throwError } from 'rxjs';
import { describe, expect, it, vi } from 'vitest';
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
    value.openSetup('simulation');
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

  it('offers only Meta-mapped campaigns for a real SMS test', () => {
    const value = component();
    value.options = [{ id: 'p1', campaigns: [
      { id: 'draft', live_test_ready: false },
      { id: 'mapped', live_test_ready: true, lead_form_id: '12345' },
    ], products: [] }];
    value.projectId = 'p1';
    value.openSetup('live_meta');
    value.leadSourceCode = 'meta';
    value.sourceChanged();
    expect(value.availableCampaigns.map((item) => item.id)).toEqual(['mapped']);
    expect(value.campaignId).toBe('mapped');
  });

  it('submits one idempotent request that creates the lead and starts real SMS', () => {
    const calls: Array<{ url: string; body: any; options: any }> = [];
    const http = {
      post: (url: string, body: any, options: any) => {
        calls.push({ url, body, options });
        return of({ conversation_id: 'live-conversation', replayed: false, provider: 'telnyx' });
      },
      get: () => of([]),
    };
    const value = component(http);
    value.options = [{ id: 'project', campaigns: [{ id: 'campaign', live_test_ready: true }], products: [{ id: 'property_type:home' }] }];
    value.projectId = 'project'; value.openSetup('live_meta');
    value.form = {
      first_name: 'Taylor', last_name: 'Morgan', phone: '+13055550142', email: 'taylor@example.com',
      product_id: 'property_type:home', budget_min: 600000, budget_max: 750000, consent: true,
    };
    value.startLiveMetaTest();
    expect(calls).toHaveLength(1);
    expect(calls[0].url.endsWith('/sales-agent/live-leads')).toBe(true);
    expect(calls[0].body.source_code).toBe('manual');
    expect(calls[0].body.campaign_id).toBeNull();
    expect(calls[0].body.lead.product_id).toBeUndefined();
    expect(calls[0].body.lead.budget_min).toBeUndefined();
    expect(calls[0].options.headers['Idempotency-Key'].length).toBeGreaterThanOrEqual(16);
    expect(value.success).toContain('Telnyx');
    expect(value.creating).toBe(false);
  });

  it('accepts the minimal live lead identity without product or budget', () => {
    const value = component();
    value.options = [{ id: 'project', campaigns: [], products: [] }];
    value.projectId = 'project';
    value.openSetup('live_meta');
    value.form.first_name = 'Taylor';
    value.form.last_name = 'Morgan';
    value.form.phone = '+51999888777';
    value.form.email = 'taylor@example.com';
    value.form.consent = true;
    expect(value.form.product_id).toBe('');
    expect(value.form.budget_min).toBeNull();
    expect(value.formComplete).toBe(true);
  });

  it('keeps progressively qualified lead facts in the live conversation context', () => {
    const value = component();
    value.selected = {
      id: 'live-conversation', channel: 'whatsapp', platform: 'manual', is_paused: false,
      qualification_summary: 'Minimum budget: 400000; Property interest: 40 Villa',
    };
    expect(value.selected.qualification_summary).toContain('Minimum budget');
    expect(value.operationalStatusLabel).toBe('AI ACTIVE');
  });

  it('shows durable turn state and safely retries a failed live response', () => {
    const calls: string[] = [];
    const value = component({
      post: (url: string) => {
        calls.push(url);
        return of({
          id: 'live-conversation', channel: 'whatsapp', is_paused: false,
          agent_turn_status: 'retry', project_timezone: 'America/Lima',
        });
      },
      get: () => of([]),
    });
    value.selected = {
      id: 'live-conversation', channel: 'whatsapp', is_paused: false,
      agent_turn_status: 'failed', agent_turn_error: 'Agent turn processing failed.',
    };
    expect(value.operationalStatusLabel).toBe('AI NEEDS ATTENTION');
    value.retryFailedTurn();
    expect(calls[0]).toContain('/conversations/live-conversation/retry-turn');
    expect(value.operationalStatusLabel).toBe('AI RETRY SCHEDULED');
    expect(value.retryingTurn).toBe(false);
  });

  it('requires a mapped campaign only when the selected source is Meta', () => {
    const value = component();
    value.options = [{ id: 'project', campaigns: [], products: [{ id: 'property_type:home' }] }];
    value.projectId = 'project'; value.openSetup('live_meta');
    value.form = {
      first_name: 'Taylor', last_name: 'Morgan', phone: '+13055550142', email: 'taylor@example.com',
      product_id: 'property_type:home', budget_min: 600000, budget_max: null, consent: true,
    };
    expect(value.leadSourceCode).toBe('manual');
    expect(value.formComplete).toBe(true);
    value.leadSourceCode = 'meta'; value.sourceChanged();
    expect(value.formComplete).toBe(false);
  });

  it('renders the safe Telnyx provider detail instead of a generic Meta error', () => {
    const http = {
      post: () => throwError(() => ({ error: { detail: {
        code: 'TELNYX_MESSAGE_REJECTED', message: 'Telnyx rejected the outbound SMS.',
        provider_detail: 'The destination is not enabled for international outbound messaging.',
      } } })),
    };
    const value = component(http);
    value.options = [{ id: 'project', campaigns: [], products: [{ id: 'property_type:home' }] }];
    value.projectId = 'project'; value.openSetup('live_meta');
    value.form = {
      first_name: 'Taylor', last_name: 'Morgan', phone: '+51999888777', email: 'taylor@example.com',
      product_id: 'property_type:home', budget_min: 600000, budget_max: null, consent: true,
    };
    value.startLiveMetaTest();
    expect(value.error).toContain('international outbound messaging');
    expect(value.error).not.toContain('Meta test');
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

  it('labels +24h and +48h follow-ups as scheduled reminders', () => {
    const value = component();
    expect(value.isReminder({ status: 'simulated_follow_up_24h' })).toBe(true);
    expect(value.reminderLabel({ status: 'simulated_follow_up_24h' })).toContain('+24h');
    expect(value.reminderLabel({ status: 'simulated_follow_up_48h' })).toContain('+48h');
  });

  it('loads every lead when the All leads filter is selected', () => {
    const urls: string[] = [];
    const value = component({ get: (url: string) => { urls.push(url); return of([]); } });
    value.projectId = '';
    value.loadConversations();
    value.refreshConversationSummaries();
    expect(urls).toHaveLength(2);
    expect(urls.every(url => url.endsWith('/sales-agent/conversations'))).toBe(true);
  });

  it('detects and opens a newly arrived Meta conversation without a page reload', () => {
    const incoming = {
      id: 'meta-conversation', lead_id: 'meta-lead', lead_name: 'Meta Lead',
      platform: 'meta', channel: 'simulation', is_paused: false,
    };
    const http = {
      get: (url: string) => url.includes('/messages') ? of([]) : of([incoming]),
    };
    const value = component(http);
    (value as any).conversationSnapshotReady = true;
    (value as any).knownConversationIds = new Set(['existing']);

    (value as any).pollConversations();

    expect(value.selected?.id).toBe('meta-conversation');
    expect(value.success).toContain('New Meta lead received');
  });

  it('refreshes the selected message thread while polling conversation summaries', () => {
    const conversation = { id: 'live-conversation', lead_id: 'lead', platform: 'manual', channel: 'sms' };
    const inbound = { id: 'inbound-1', direction: 'inbound', content: 'Hello', created_at: '2026-09-27T00:11:28Z' };
    const http = {
      get: (url: string) => url.includes('/messages') ? of([inbound]) : of([conversation]),
    };
    const value = component(http);
    value.selected = conversation;
    (value as any).conversationSnapshotReady = true;
    (value as any).knownConversationIds = new Set(['live-conversation']);

    (value as any).pollConversations();

    expect(value.messages).toEqual([inbound]);
  });

  it('deletes only the selected synthetic Agent lead and clears its conversation', () => {
    const calls: string[] = [];
    const confirmation = vi.spyOn(window, 'confirm').mockReturnValue(true);
    const value = component({ delete: (url: string) => { calls.push(url); return of(null); } });
    value.selected = {
      id: 'conversation-1', simulation_id: 'simulation-1', platform: 'demo_meta_form',
      lead_name: 'Synthetic Lead',
    };
    value.conversations = [value.selected];

    value.deleteSelectedSimulation();

    expect(calls[0]).toContain('/sales-agent/simulations/simulation-1');
    expect(value.conversations).toEqual([]);
    expect(value.selected).toBeNull();
    expect(value.success).toContain('synthetic lead');
    confirmation.mockRestore();
  });

  it('never exposes synthetic deletion for a real Meta lead', () => {
    const value = component();
    value.selected = { id: 'real', platform: 'meta', simulation_id: null };
    expect(value.canDeleteSimulation).toBe(false);
  });

  it('sends with Enter, preserves Shift+Enter and ignores IME composition', () => {
    const value = component();
    let sends = 0;
    value.send = () => { sends += 1; };
    const enter = { key: 'Enter', shiftKey: false, isComposing: false, preventDefault: () => undefined } as any;
    value.onComposerKeydown(enter);
    value.onComposerKeydown({ ...enter, shiftKey: true });
    value.onComposerKeydown({ ...enter, isComposing: true });
    expect(sends).toBe(1);
  });

  it('renders the lead message optimistically while the AI turn is pending', () => {
    let observer: any;
    const value = component({ post: () => ({ pipe: () => ({ subscribe: (next: any) => { observer = next; } }) }) });
    value.selected = { id: 'conversation', lead_id: 'lead', channel: 'simulation', is_paused: false };
    value.draft = 'towards the down payment';
    value.send();
    expect(value.draft).toBe('');
    expect(value.messages.at(-1)?.content).toBe('towards the down payment');
    expect(value.messages.at(-1)?.status).toBe('sending');
    expect(value.sending).toBe(true);
    expect(observer).toBeTruthy();
  });

  it('treats WhatsApp as a live provider conversation and never as a simulation', () => {
    const urls: string[] = [];
    const value = component({
      post: (url: string) => {
        urls.push(url);
        return { pipe: () => ({ subscribe: () => undefined }) };
      },
    });
    value.selected = {
      id: 'whatsapp-conversation', lead_id: 'lead', channel: 'whatsapp', is_paused: true,
      pause_reason: 'Human intervention: review',
    };
    value.draft = 'Manual takeover message';
    expect(value.isLive).toBe(true);
    expect(value.liveControlLabel).toBe('LIVE WHATSAPP CONTROL');
    expect(value.operationalStatusLabel).toBe('HUMAN CONTROL');
    value.send();
    expect(urls[0]).toContain('/conversations/whatsapp-conversation/manual-message');
    expect(urls[0]).not.toContain('/simulate');
  });

  it('marks timezone-less backend timestamps as UTC before rendering', () => {
    const value = component();
    expect(value.asUtcDate('2026-09-30T22:52:00')).toBe('2026-09-30T22:52:00Z');
    expect(value.asUtcDate('2026-09-30T22:52:00Z')).toBe('2026-09-30T22:52:00Z');
    expect(value.asUtcDate('2026-09-30T17:52:00-05:00')).toBe('2026-09-30T17:52:00-05:00');
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
