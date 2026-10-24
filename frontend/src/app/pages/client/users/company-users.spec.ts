import '@angular/compiler';
import { describe, expect, it } from 'vitest';
import { CompanyUsersComponent } from './company-users';

describe('CompanyUsersComponent', () => {
  it('defaults a new user to the authoritative Company timezone', () => {
    const component = new CompanyUsersComponent({} as any, {} as any, {} as any);
    component.companyTimezone = 'America/Lima';

    component.openAddModal();

    expect(component.invite.timezone).toBe('America/Lima');
  });

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

  it('reuses an invitation key only while the submitted data remains unchanged', () => {
    const component = new CompanyUsersComponent({} as any, {} as any, {} as any);
    component.invite = {
      first_name: 'Ana', last_name: 'Sales', email: 'ana@example.com', role: 'sales',
      is_active: true, timezone: 'America/Lima', project_access_scope: 'all', project_ids: [],
    };
    const requestKey = () => (component as any).invitationRequestKey() as string;
    const first = requestKey();
    expect(requestKey()).toBe(first);
    component.invite.email = 'other@example.com';
    expect(requestKey()).not.toBe(first);
  });

  it('presents Firebase quota exhaustion as a recoverable saved-user state', () => {
    const component = new CompanyUsersComponent({} as any, {} as any, {} as any);
    const user = {
      id: 'user-1', email: 'quota@example.com', role: 'sales', is_active: true,
      project_assignment_required: false, auth_status: 'provisioning_failed',
      invitation_delivery: 'failed', invitation_error_code: 'QUOTA_EXCEEDED',
      invitation_error_message: 'Firebase has exhausted the daily email-link quota. Use Resend invitation after it resets.',
    } as const;

    expect(component.authStatusLabel(user)).toBe('Email quota exceeded');
    expect((component as any).invitationResultMessage(user)).toContain('User quota@example.com was saved.');
    expect((component as any).invitationResultMessage(user)).toContain('Use Resend invitation');
  });

  it('loads the administrator operational roles without changing the administrator identity', () => {
    const component = new CompanyUsersComponent({} as any, {} as any, {} as any);
    const administrator = {
      id: 'admin-1', email: 'admin@example.com', first_name: 'Company', last_name: 'Admin',
      role: 'admin', is_active: true, project_access_scope: 'selected', project_ids: ['project-1'],
      project_assignment_required: false, auth_status: 'active', sales_enabled: true,
      marketing_enabled: true, accepts_new_leads: false, accepts_appointments: true,
    } as any;
    component.users = [administrator];

    component.openEditModal(administrator);

    expect(component.editingAdministrator).toBe(true);
    expect(component.invite.role).toBe('admin');
    expect(component.invite.project_ids).toEqual(['project-1']);
    expect(component.invite.sales_enabled).toBe(true);
    expect(component.invite.marketing_enabled).toBe(true);
    expect(component.invite.accepts_new_leads).toBe(false);
    expect(component.invite.accepts_appointments).toBe(true);
  });
});
