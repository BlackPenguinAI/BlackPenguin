import '@angular/compiler';
import { describe, expect, it } from 'vitest';
import { MessagingSettingsPageComponent } from './messaging-settings-page';

describe('MessagingSettingsPageComponent', () => {
  it('does not test credentials while unsaved values are present', () => {
    let error = '';
    const component = new MessagingSettingsPageComponent({ post: () => { throw new Error('must not call'); } } as any, { showError: (value: string) => error = value } as any, {} as any);
    component.dirty.twilio = true;
    component.verify('twilio');
    expect(error).toContain('Save');
  });

  it('does not allow an unverified provider to become the default', () => {
    const component = new MessagingSettingsPageComponent({ put: () => { throw new Error('must not call'); } } as any, {} as any, {} as any);
    component.defaultProvider = 'twilio';
    component.telnyx.verification_status = 'pending';
    component.telnyx.live_sms_enabled = false;
    expect(component.defaultProvider).toBe('twilio');
  });

  it('does not verify a Company sender while it has unsaved changes', () => {
    let error = '';
    const component = new MessagingSettingsPageComponent(
      { post: () => { throw new Error('must not call'); } } as any,
      { showError: (value: string) => error = value } as any,
      {} as any,
    );
    component.telnyxCompanies = [{
      id: null, company_id: 'company-1', company_name: 'Acme', company_is_active: true,
      messaging_profile_id: 'profile-1', from_phone_number: '+13055550142',
      telnyx_phone_number_id: '', regulatory_status: 'approved', live_sms_enabled: false,
      verification_status: 'pending', verified_at: null, last_error: '',
    }];
    component.selectedCompanyId = 'company-1';
    component.dirty.telnyxCompany = true;
    component.verifyTelnyxCompany();
    expect(error).toContain('Save Company');
  });

  it('counts only verified and enabled Company senders', () => {
    const component = new MessagingSettingsPageComponent({} as any, {} as any, {} as any);
    component.telnyxCompanies = [
      { id: '1', company_id: 'a', company_name: 'A', company_is_active: true, messaging_profile_id: 'p-a', from_phone_number: '+1', telnyx_phone_number_id: '', regulatory_status: 'approved', live_sms_enabled: true, verification_status: 'verified', verified_at: null, last_error: '' },
      { id: '2', company_id: 'b', company_name: 'B', company_is_active: true, messaging_profile_id: 'p-b', from_phone_number: '+2', telnyx_phone_number_id: '', regulatory_status: 'pending', live_sms_enabled: false, verification_status: 'pending', verified_at: null, last_error: '' },
    ];
    expect(component.configuredCompanyCount).toBe(1);
  });
});
