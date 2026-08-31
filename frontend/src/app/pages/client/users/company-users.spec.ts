import '@angular/compiler';
import { describe, expect, it } from 'vitest';
import { CompanyUsersComponent } from './company-users';

describe('CompanyUsersComponent', () => {
  it('validates identity fields without asking for an initial password', () => {
    const component = new CompanyUsersComponent({} as any, {} as any, {} as any);
    component.invite = {
      first_name: 'Ana', last_name: 'Sales', email: 'ana@example.com', role: 'sales',
      is_active: true, timezone: 'America/Lima', project_access_scope: 'all', project_ids: [],
    };
    expect(component.formValid).toBe(true);
    component.invite.email = 'invalid';
    expect(component.formValid).toBe(false);
  });
});
