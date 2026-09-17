import '@angular/compiler';
import { of, throwError } from 'rxjs';
import { describe, expect, it, vi } from 'vitest';
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

  it('renders nested source data as structured rows instead of JSON text', () => {
    const value = component();
    const rows = value.dataRows({
      selected_product: { name: 'Shoreline Collection', available_units: 3 },
      budget: { minimum: 500000, currency: 'USD' },
    });

    expect(rows.some(row => row.group && row.label === 'Selected product')).toBe(true);
    expect(rows.some(row => row.label === 'Name' && row.value === 'Shoreline Collection')).toBe(true);
    expect(rows.some(row => row.label === 'Minimum' && row.value === '500,000')).toBe(true);
    expect(rows.every(row => !row.value.includes('{'))).toBe(true);
    expect(value.structuredSummary('{"budget":{"minimum":500000}}')).toEqual({ budget: { minimum: 500000 } });
    expect(value.structuredSummary('Human-readable summary')).toBeNull();
  });

  it('opens the lead referenced by a notification after the list loads', () => {
    const lead = { id: 'lead-1', full_name: 'Interested Lead', phone: '+15550001' };
    const http = { get: (url: string) => of(url.includes('/leads/lead-1') ? lead : [lead]) };
    const value = new LeadsComponent(
      http as any,
      { markForCheck: () => undefined } as any,
      { navigate: () => Promise.resolve(true) } as any,
      { snapshot: { queryParamMap: { get: (key: string) => key === 'lead' ? 'lead-1' : null } } } as any,
    );
    value.ngOnInit();
    expect(value.selected).toEqual(lead);
  });

  it('loads superadmin leads even when the project filter request fails', () => {
    const lead = { id: 'legacy-lead', project_id: null, full_name: 'Legacy Lead' };
    const http = { get: vi.fn((url: string) => url.includes('/admin/companies/') ? throwError(() => new Error('failed')) : of([lead])) };
    const value = new LeadsComponent(
      http as any,
      { markForCheck: () => undefined } as any,
      { navigate: () => Promise.resolve(true) } as any,
    );
    Object.defineProperty(value, 'isSuperadmin', { value: true });
    value.companyId = 'company-1';

    value.selectCompany();

    expect(value.leads).toEqual([lead]);
    expect(http.get).toHaveBeenCalledWith(expect.stringContaining('/sales/admin/leads?company_id=company-1'));
  });

  it('exports the active filters and downloads an individual Lead Record', () => {
    const calls: Array<{ url: string; options: any }> = [];
    const http = { get: (url: string, options: any) => { calls.push({ url, options }); return of(new Blob(['ok'])); } };
    const value = new LeadsComponent(
      http as any,
      { markForCheck: () => undefined } as any,
      { navigate: () => Promise.resolve(true) } as any,
    );
    const files: string[] = [];
    (value as any).saveBlob = (_blob: Blob, filename: string) => files.push(filename);
    value.projectId = 'project-1'; value.tier = 'hot'; value.search = 'George';
    value.selected = { id: 'lead-1' };

    value.exportCurrentView();
    value.downloadSourceData();

    expect(calls[0].url).toContain('/sales/leads/export.csv?');
    expect(calls[0].url).toContain('project_id=project-1');
    expect(calls[0].url).toContain('tier=hot');
    expect(calls[0].url).toContain('search=George');
    expect(calls[0].options.responseType).toBe('blob');
    expect(calls[1].url).toContain('/sales/leads/lead-1/export.json');
    expect(files[1]).toBe('black-penguin-lead-lead-1.json');
  });
});
