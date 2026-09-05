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
});
