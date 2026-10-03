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

  it('selects a WhatsApp number returned by the Company WABA', () => {
    const component = new MessagingSettingsPageComponent({} as any, {} as any, {} as any);
    const company: any = {
      id: '1', company_id: 'a', company_name: 'A', company_is_active: true,
      whatsapp_business_account_id: 'waba-1', whatsapp_phone_number_id: '',
      whatsapp_from_phone_number: '', verification_status: 'verified',
    };
    component.whatsappAccounts = [{ id: 'waba-1', phone_numbers: [{
      phone_number_id: 'phone-1', phone_number: '+51999000111', status: 'verified',
    }] }];
    component.selectWhatsAppNumber(company, 'phone-1');
    expect(company.whatsapp_from_phone_number).toBe('+51999000111');
    expect(component.dirty.telnyxCompany).toBe(true);
  });

  it('keeps the lead-visible template snapshot with the selected template', () => {
    const component = new MessagingSettingsPageComponent({} as any, {} as any, {} as any);
    const company: any = {};
    component.whatsappTemplates = [{
      name: 'welcome_en', language: 'en_US', content: 'Hi {{1}}, welcome to {{2}}.', status: 'approved',
    }];
    component.selectWhatsAppTemplate(company, 'welcome_en|en_US');
    expect(company.whatsapp_template_name).toBe('welcome_en');
    expect(company.whatsapp_template_language).toBe('en_US');
    expect(company.whatsapp_template_content).toBe('Hi {{1}}, welcome to {{2}}.');
    expect(component.whatsappTemplatePreview(company)).toBe('Hi Alex, welcome to Example Project.');
    expect(component.dirty.telnyxCompany).toBe(true);
  });

  it('accepts only the English two-parameter initial template contract', () => {
    const component = new MessagingSettingsPageComponent({} as any, {} as any, {} as any);
    expect(component.isCompatibleInitialTemplate('Hi {{1}}, welcome to {{2}}.')).toBe(true);
    expect(component.isCompatibleInitialTemplate('Welcome to Black Penguin.')).toBe(false);
    expect(component.isCompatibleInitialTemplate('Hi {{1}}, reference {{3}}.')).toBe(false);
  });

  it('saves a WhatsApp-only Company without requiring an SMS sender', () => {
    let requested = false;
    const response = { subscribe: ({ next }: any) => { requested = true; next({ company_id: 'a', company_name: 'A' }); } };
    const component = new MessagingSettingsPageComponent(
      { put: () => response } as any,
      { showError: () => { throw new Error('must not reject'); }, showSuccess: () => undefined } as any,
      { detectChanges: () => undefined } as any,
    );
    component.telnyxCompanies = [{
      id: '1', company_id: 'a', company_name: 'A', company_is_active: true,
      messaging_profile_id: 'profile-1', from_phone_number: '', telnyx_phone_number_id: '',
      regulatory_status: 'not_required', live_sms_enabled: false, primary_channel: 'whatsapp',
      live_whatsapp_enabled: false, verification_status: 'not_configured', verified_at: null, last_error: '',
    }];
    component.selectedCompanyId = 'a';
    component.saveTelnyxCompany();
    expect(requested).toBe(true);
  });
});
