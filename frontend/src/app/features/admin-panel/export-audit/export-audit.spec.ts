import '@angular/compiler';
import { of } from 'rxjs';
import { describe, expect, it, vi } from 'vitest';
import { ExportAuditComponent } from './export-audit';

describe('ExportAuditComponent', () => {
  it('loads filtered immutable export events and resolves the Company name', () => {
    const http = { get: vi.fn().mockReturnValue(of([])) } as any;
    const component = new ExportAuditComponent(http, { markForCheck: vi.fn() } as any);
    component.companies = [{ id: 'company-1', name: 'Northstar' }];
    component.companyId = 'company-1';
    component.exportType = 'leads_csv';
    component.load();
    expect(http.get).toHaveBeenCalledWith(expect.stringContaining('company_id=company-1&export_type=leads_csv'));
    expect(component.companyName('company-1')).toBe('Northstar');
  });
});
