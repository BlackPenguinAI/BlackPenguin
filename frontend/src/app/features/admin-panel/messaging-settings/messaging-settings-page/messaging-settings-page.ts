import { Component, OnInit, ChangeDetectorRef, isDevMode } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { forkJoin } from 'rxjs';
import { ToastService } from '../../../../core/services/toast';
import { GlassCardComponent } from '../../../../shared/ui/glass-card/glass-card';
import { InputComponent } from '../../../../shared/ui/input/input';
import { ButtonComponent } from '../../../../shared/ui/button/button';

type Provider = 'twilio' | 'telnyx';
type RegulatoryStatus = 'pending' | 'approved' | 'not_required';
type MessagingChannel = 'sms' | 'whatsapp';

interface TelnyxCompanySender {
  id: string | null;
  company_id: string;
  company_name: string;
  company_is_active: boolean;
  country_code?: string | null;
  messaging_profile_id: string;
  from_phone_number: string;
  telnyx_phone_number_id: string;
  sender_country_code?: string | null;
  coverage_snapshot?: {
    note?: string;
    destinations?: Array<{
      country_code: string;
      country_name: string;
      outbound: boolean;
      inbound: boolean;
      conversational: boolean;
      route_identity: string;
      status: string;
    }>;
  };
  coverage_checked_at?: string | null;
  regulatory_status: RegulatoryStatus;
  live_sms_enabled: boolean;
  primary_channel?: MessagingChannel;
  whatsapp_business_account_id?: string;
  whatsapp_phone_number_id?: string;
  whatsapp_from_phone_number?: string;
  whatsapp_template_name?: string;
  whatsapp_template_language?: string;
  whatsapp_template_content?: string;
  live_whatsapp_enabled?: boolean;
  whatsapp_verification_status?: string;
  whatsapp_verified_at?: string | null;
  whatsapp_last_error?: string;
  verification_status: string;
  verified_at: string | null;
  last_error: string;
}

@Component({
  selector: 'app-messaging-settings-page',
  standalone: true,
  imports: [CommonModule, FormsModule, GlassCardComponent, InputComponent, ButtonComponent],
  templateUrl: './messaging-settings-page.html'
})
export class MessagingSettingsPageComponent implements OnInit {
  defaultProvider: Provider = 'twilio';
  twilio = { account_sid: '', auth_token: '', from_phone_number: '', auth_token_configured: false, auth_token_hint: '', live_sms_enabled: false, verification_status: 'not_configured', verified_at: null as string | null, last_error: '' };
  telnyx = { api_key: '', webhook_public_key: '', api_key_configured: false, api_key_hint: '', webhook_public_key_configured: false, live_sms_enabled: false, verification_status: 'not_configured', verified_at: null as string | null, last_error: '' };
  telnyxCompanies: TelnyxCompanySender[] = [];
  whatsappAccounts: any[] = [];
  whatsappTemplates: any[] = [];
  loadingWhatsAppResources = false;
  selectedCompanyId = '';
  isLoading = true;
  saving = '';
  verifying = '';
  switching = false;
  dirty = { twilio: false, telnyx: false, telnyxCompany: false };

  constructor(private http: HttpClient, private toast: ToastService, private cdr: ChangeDetectorRef) {}
  ngOnInit() { this.load(); }
  private get baseUrl() { return isDevMode() ? 'http://localhost:8000' : 'https://blackpenguin.ai'; }
  private get headers() { return new HttpHeaders().set('Authorization', `Bearer ${localStorage.getItem('bp_token')}`); }
  private message(error: any, fallback: string) {
    const detail = error?.error?.detail;
    return typeof detail === 'string' ? detail : (detail?.message || fallback);
  }

  get selectedCompany(): TelnyxCompanySender | undefined {
    return this.telnyxCompanies.find(item => item.company_id === this.selectedCompanyId);
  }

  get configuredCompanyCount() {
    return this.telnyxCompanies.filter(item => item.live_sms_enabled && item.verification_status === 'verified').length;
  }

  load() {
    this.isLoading = true;
    forkJoin({
      twilio: this.http.get<any>(`${this.baseUrl}/api/v1/system/messaging-settings`, { headers: this.headers }),
      telnyx: this.http.get<any>(`${this.baseUrl}/api/v1/system/messaging-settings/telnyx`, { headers: this.headers }),
      telnyxCompanies: this.http.get<TelnyxCompanySender[]>(`${this.baseUrl}/api/v1/system/messaging-settings/telnyx/companies`, { headers: this.headers }),
      routing: this.http.get<any>(`${this.baseUrl}/api/v1/system/messaging-settings/default-provider`, { headers: this.headers }),
    }).subscribe({
      next: data => {
        this.twilio = { ...this.twilio, ...data.twilio, auth_token: '' };
        this.telnyx = { ...this.telnyx, ...data.telnyx, api_key: '', webhook_public_key: '' };
        this.telnyxCompanies = data.telnyxCompanies.map(item => ({
          ...item,
          messaging_profile_id: item.messaging_profile_id || '',
          from_phone_number: item.from_phone_number || '',
          telnyx_phone_number_id: item.telnyx_phone_number_id || '',
          primary_channel: item.primary_channel || (item.country_code === 'US' ? 'sms' : 'whatsapp'),
          whatsapp_business_account_id: item.whatsapp_business_account_id || '',
          whatsapp_phone_number_id: item.whatsapp_phone_number_id || '',
          whatsapp_from_phone_number: item.whatsapp_from_phone_number || '',
          whatsapp_template_name: item.whatsapp_template_name || '',
          whatsapp_template_language: item.whatsapp_template_language || 'en_US',
          whatsapp_template_content: item.whatsapp_template_content || '',
          live_whatsapp_enabled: !!item.live_whatsapp_enabled,
          whatsapp_verification_status: item.whatsapp_verification_status || 'not_configured',
          whatsapp_verified_at: item.whatsapp_verified_at || null,
          whatsapp_last_error: item.whatsapp_last_error || '',
          coverage_snapshot: item.coverage_snapshot || {},
          last_error: item.last_error || '',
        }));
        if (!this.selectedCompanyId || !this.telnyxCompanies.some(item => item.company_id === this.selectedCompanyId)) {
          this.selectedCompanyId = this.telnyxCompanies[0]?.company_id || '';
        }
        this.defaultProvider = data.routing.default_provider || 'twilio';
        this.dirty = { twilio: false, telnyx: false, telnyxCompany: false };
        this.isLoading = false; this.cdr.detectChanges();
      },
      error: err => { this.isLoading = false; this.toast.showError(this.message(err, 'Failed to load messaging providers.')); this.cdr.detectChanges(); }
    });
  }

  selectCompany(companyId: string) {
    if (this.dirty.telnyxCompany) {
      this.toast.showError('Save or reload the current Company sender before switching.');
      return;
    }
    this.selectedCompanyId = companyId;
  }

  saveTwilio() {
    if (!this.twilio.account_sid || (!this.twilio.auth_token && !this.twilio.auth_token_configured) || !this.twilio.from_phone_number) {
      this.toast.showError('Complete the Twilio Account SID, Auth Token and From number.'); return;
    }
    const payload: any = { account_sid: this.twilio.account_sid, from_phone_number: this.twilio.from_phone_number, live_sms_enabled: this.twilio.live_sms_enabled };
    if (this.twilio.auth_token) payload.auth_token = this.twilio.auth_token;
    this.saving = 'twilio';
    this.http.put<any>(`${this.baseUrl}/api/v1/system/messaging-settings`, payload, { headers: this.headers }).subscribe({
      next: data => { this.twilio = { ...this.twilio, ...data, auth_token: '' }; this.dirty.twilio = false; this.saving = ''; this.toast.showSuccess('Twilio settings saved.'); this.cdr.detectChanges(); },
      error: err => { this.saving = ''; this.toast.showError(this.message(err, 'Twilio settings could not be saved.')); this.cdr.detectChanges(); }
    });
  }

  saveTelnyx() {
    if ((!this.telnyx.api_key && !this.telnyx.api_key_configured) || (!this.telnyx.webhook_public_key && !this.telnyx.webhook_public_key_configured)) {
      this.toast.showError('Complete the Telnyx API Key and webhook public key.'); return;
    }
    const payload: any = { live_sms_enabled: this.telnyx.live_sms_enabled };
    if (this.telnyx.api_key) payload.api_key = this.telnyx.api_key;
    if (this.telnyx.webhook_public_key) payload.webhook_public_key = this.telnyx.webhook_public_key;
    this.saving = 'telnyx';
    this.http.put<any>(`${this.baseUrl}/api/v1/system/messaging-settings/telnyx`, payload, { headers: this.headers }).subscribe({
      next: data => { this.telnyx = { ...this.telnyx, ...data, api_key: '', webhook_public_key: '' }; this.dirty.telnyx = false; this.saving = ''; this.toast.showSuccess('Telnyx platform credentials saved.'); this.cdr.detectChanges(); },
      error: err => { this.saving = ''; this.toast.showError(this.message(err, 'Telnyx settings could not be saved.')); this.cdr.detectChanges(); }
    });
  }

  saveTelnyxCompany() {
    const company = this.selectedCompany;
    if (!company) return;
    if (!company.messaging_profile_id) {
      this.toast.showError('Complete the Company Messaging Profile ID.'); return;
    }
    if ((company.primary_channel === 'sms' || company.live_sms_enabled) && !company.from_phone_number) {
      this.toast.showError('Complete the Company SMS From number.'); return;
    }
    const payload = {
      country_code: company.country_code,
      messaging_profile_id: company.messaging_profile_id,
      from_phone_number: company.from_phone_number,
      telnyx_phone_number_id: company.telnyx_phone_number_id || null,
      regulatory_status: company.regulatory_status,
      live_sms_enabled: company.live_sms_enabled,
      primary_channel: company.primary_channel,
      whatsapp_business_account_id: company.whatsapp_business_account_id || null,
      whatsapp_phone_number_id: company.whatsapp_phone_number_id || null,
      whatsapp_from_phone_number: company.whatsapp_from_phone_number || null,
      whatsapp_template_name: company.whatsapp_template_name || null,
      whatsapp_template_language: company.whatsapp_template_language || 'en_US',
      whatsapp_template_content: company.whatsapp_template_content || null,
      live_whatsapp_enabled: company.live_whatsapp_enabled,
    };
    this.saving = `company:${company.company_id}`;
    this.http.put<TelnyxCompanySender>(`${this.baseUrl}/api/v1/system/messaging-settings/telnyx/companies/${company.company_id}`, payload, { headers: this.headers }).subscribe({
      next: data => { this.replaceCompany(data); this.dirty.telnyxCompany = false; this.saving = ''; this.toast.showSuccess(`${data.company_name} sender saved.`); this.cdr.detectChanges(); },
      error: err => { this.saving = ''; this.toast.showError(this.message(err, 'Company sender could not be saved.')); this.cdr.detectChanges(); }
    });
  }

  verify(provider: Provider) {
    if (this.dirty[provider]) { this.toast.showError('Save changes before testing stored credentials.'); return; }
    this.verifying = provider;
    const suffix = provider === 'twilio' ? '' : '/telnyx';
    this.http.post<any>(`${this.baseUrl}/api/v1/system/messaging-settings${suffix}/verify`, {}, { headers: this.headers }).subscribe({
      next: data => { provider === 'twilio' ? this.twilio = { ...this.twilio, ...data } : this.telnyx = { ...this.telnyx, ...data }; this.verifying = ''; this.toast.showSuccess(`${provider === 'twilio' ? 'Twilio' : 'Telnyx platform'} credentials verified.`); this.cdr.detectChanges(); },
      error: err => { this.verifying = ''; this.toast.showError(this.message(err, `${provider} verification failed.`)); this.cdr.detectChanges(); }
    });
  }

  verifyTelnyxCompany() {
    const company = this.selectedCompany;
    if (!company) return;
    if (this.dirty.telnyxCompany) { this.toast.showError('Save Company changes before verification.'); return; }
    this.verifying = `company:${company.company_id}`;
    this.http.post<TelnyxCompanySender>(`${this.baseUrl}/api/v1/system/messaging-settings/telnyx/companies/${company.company_id}/verify`, {}, { headers: this.headers }).subscribe({
      next: data => { this.replaceCompany(data); this.verifying = ''; this.toast.showSuccess(`${data.company_name} sender verified.`); this.cdr.detectChanges(); },
      error: err => { this.verifying = ''; this.toast.showError(this.message(err, 'Company sender verification failed.')); this.cdr.detectChanges(); }
    });
  }

  loadWhatsAppResources() {
    if (this.dirty.telnyx) { this.toast.showError('Save and verify Telnyx platform credentials first.'); return; }
    this.loadingWhatsAppResources = true;
    this.http.get<any>(`${this.baseUrl}/api/v1/system/messaging-settings/telnyx/whatsapp/resources`, { headers: this.headers }).subscribe({
      next: data => {
        this.whatsappAccounts = data.business_accounts || [];
        this.whatsappTemplates = (data.templates || []).filter((item: any) => ['approved', 'active'].includes(String(item.status).toLowerCase()));
        this.loadingWhatsAppResources = false;
        this.cdr.detectChanges();
      },
      error: err => { this.loadingWhatsAppResources = false; this.toast.showError(this.message(err, 'WhatsApp resources could not be loaded from Telnyx.')); this.cdr.detectChanges(); }
    });
  }

  whatsappNumbers(company: TelnyxCompanySender): any[] {
    return this.whatsappAccounts.find(item => item.id === company.whatsapp_business_account_id)?.phone_numbers || [];
  }

  selectWhatsAppNumber(company: TelnyxCompanySender, phoneNumberId: string) {
    company.whatsapp_phone_number_id = phoneNumberId;
    const item = this.whatsappNumbers(company).find(number => String(number.phone_number_id || number.id) === phoneNumberId);
    company.whatsapp_from_phone_number = item?.phone_number || '';
    this.dirty.telnyxCompany = true;
  }

  selectWhatsAppTemplate(company: TelnyxCompanySender, value: string) {
    const [name, language] = value.split('|');
    company.whatsapp_template_name = name || '';
    company.whatsapp_template_language = language || 'en_US';
    const template = this.whatsappTemplates.find(item => item.name === name && item.language === language);
    company.whatsapp_template_content = template?.content || '';
    this.dirty.telnyxCompany = true;
  }

  verifyTelnyxWhatsApp() {
    const company = this.selectedCompany;
    if (!company) return;
    if (this.dirty.telnyxCompany) { this.toast.showError('Save Company changes before verification.'); return; }
    this.verifying = `whatsapp:${company.company_id}`;
    this.http.post<TelnyxCompanySender>(`${this.baseUrl}/api/v1/system/messaging-settings/telnyx/companies/${company.company_id}/verify-whatsapp`, {}, { headers: this.headers }).subscribe({
      next: data => { this.replaceCompany(data); this.verifying = ''; this.toast.showSuccess(`${data.company_name} WhatsApp sender verified.`); this.cdr.detectChanges(); },
      error: err => { this.verifying = ''; this.toast.showError(this.message(err, 'Company WhatsApp verification failed.')); this.cdr.detectChanges(); }
    });
  }

  private replaceCompany(data: TelnyxCompanySender) {
    const index = this.telnyxCompanies.findIndex(item => item.company_id === data.company_id);
    if (index >= 0) this.telnyxCompanies[index] = { ...this.telnyxCompanies[index], ...data };
  }

  setDefault(provider: Provider) {
    if (provider === this.defaultProvider) return;
    this.switching = true;
    this.http.put<any>(`${this.baseUrl}/api/v1/system/messaging-settings/default-provider`, { default_provider: provider }, { headers: this.headers }).subscribe({
      next: data => { this.defaultProvider = data.default_provider; this.switching = false; this.toast.showSuccess(`${provider === 'twilio' ? 'Twilio' : 'Telnyx'} is now the default for new conversations.`); this.cdr.detectChanges(); },
      error: err => { this.switching = false; this.toast.showError(this.message(err, 'Default provider could not be changed.')); this.cdr.detectChanges(); }
    });
  }
}
