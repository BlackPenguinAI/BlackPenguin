import { Component, OnInit, ChangeDetectorRef, isDevMode } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { forkJoin } from 'rxjs';
import { ToastService } from '../../../../core/services/toast';
import { GlassCardComponent } from '../../../../shared/ui/glass-card/glass-card';
import { InputComponent } from '../../../../shared/ui/input/input';
import { ButtonComponent } from '../../../../shared/ui/button/button';

@Component({
  selector: 'app-messaging-settings-page',
  standalone: true,
  imports: [CommonModule, FormsModule, GlassCardComponent, InputComponent, ButtonComponent],
  templateUrl: './messaging-settings-page.html'
})
export class MessagingSettingsPageComponent implements OnInit {
  defaultProvider: 'twilio' | 'telnyx' = 'twilio';
  twilio = { account_sid: '', auth_token: '', from_phone_number: '', auth_token_configured: false, auth_token_hint: '', live_sms_enabled: false, verification_status: 'not_configured', verified_at: null as string | null, last_error: '' };
  telnyx = { api_key: '', messaging_profile_id: '', from_phone_number: '', webhook_public_key: '', api_key_configured: false, api_key_hint: '', webhook_public_key_configured: false, live_sms_enabled: false, verification_status: 'not_configured', verified_at: null as string | null, last_error: '' };
  isLoading = true;
  saving = '';
  verifying = '';
  switching = false;
  dirty = { twilio: false, telnyx: false };

  constructor(private http: HttpClient, private toast: ToastService, private cdr: ChangeDetectorRef) {}
  ngOnInit() { this.load(); }
  private get baseUrl() { return isDevMode() ? 'http://localhost:8000' : 'https://blackpenguin.ai'; }
  private get headers() { return new HttpHeaders().set('Authorization', `Bearer ${localStorage.getItem('bp_token')}`); }
  private message(error: any, fallback: string) {
    const detail = error?.error?.detail;
    return typeof detail === 'string' ? detail : (detail?.message || fallback);
  }

  load() {
    this.isLoading = true;
    forkJoin({
      twilio: this.http.get<any>(`${this.baseUrl}/api/v1/system/messaging-settings`, { headers: this.headers }),
      telnyx: this.http.get<any>(`${this.baseUrl}/api/v1/system/messaging-settings/telnyx`, { headers: this.headers }),
      routing: this.http.get<any>(`${this.baseUrl}/api/v1/system/messaging-settings/default-provider`, { headers: this.headers }),
    }).subscribe({
      next: data => {
        this.twilio = { ...this.twilio, ...data.twilio, auth_token: '' };
        this.telnyx = { ...this.telnyx, ...data.telnyx, api_key: '', webhook_public_key: '' };
        this.defaultProvider = data.routing.default_provider || 'twilio';
        this.dirty = { twilio: false, telnyx: false }; this.isLoading = false; this.cdr.detectChanges();
      },
      error: err => { this.isLoading = false; this.toast.showError(this.message(err, 'Failed to load messaging providers.')); this.cdr.detectChanges(); }
    });
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
    if ((!this.telnyx.api_key && !this.telnyx.api_key_configured) || !this.telnyx.messaging_profile_id || !this.telnyx.from_phone_number || (!this.telnyx.webhook_public_key && !this.telnyx.webhook_public_key_configured)) {
      this.toast.showError('Complete the Telnyx API Key, Messaging Profile, From number and webhook public key.'); return;
    }
    const payload: any = { messaging_profile_id: this.telnyx.messaging_profile_id, from_phone_number: this.telnyx.from_phone_number, live_sms_enabled: this.telnyx.live_sms_enabled };
    if (this.telnyx.api_key) payload.api_key = this.telnyx.api_key;
    if (this.telnyx.webhook_public_key) payload.webhook_public_key = this.telnyx.webhook_public_key;
    this.saving = 'telnyx';
    this.http.put<any>(`${this.baseUrl}/api/v1/system/messaging-settings/telnyx`, payload, { headers: this.headers }).subscribe({
      next: data => { this.telnyx = { ...this.telnyx, ...data, api_key: '', webhook_public_key: '' }; this.dirty.telnyx = false; this.saving = ''; this.toast.showSuccess('Telnyx settings saved.'); this.cdr.detectChanges(); },
      error: err => { this.saving = ''; this.toast.showError(this.message(err, 'Telnyx settings could not be saved.')); this.cdr.detectChanges(); }
    });
  }

  verify(provider: 'twilio' | 'telnyx') {
    if (this.dirty[provider]) { this.toast.showError('Save changes before testing stored credentials.'); return; }
    this.verifying = provider;
    const suffix = provider === 'twilio' ? '' : '/telnyx';
    this.http.post<any>(`${this.baseUrl}/api/v1/system/messaging-settings${suffix}/verify`, {}, { headers: this.headers }).subscribe({
      next: data => { provider === 'twilio' ? this.twilio = { ...this.twilio, ...data } : this.telnyx = { ...this.telnyx, ...data }; this.verifying = ''; this.toast.showSuccess(`${provider === 'twilio' ? 'Twilio' : 'Telnyx'} credentials verified.`); this.cdr.detectChanges(); },
      error: err => { this.verifying = ''; this.toast.showError(this.message(err, `${provider} verification failed.`)); this.cdr.detectChanges(); }
    });
  }

  setDefault(provider: 'twilio' | 'telnyx') {
    if (provider === this.defaultProvider) return;
    this.switching = true;
    this.http.put<any>(`${this.baseUrl}/api/v1/system/messaging-settings/default-provider`, { default_provider: provider }, { headers: this.headers }).subscribe({
      next: data => { this.defaultProvider = data.default_provider; this.switching = false; this.toast.showSuccess(`${provider === 'twilio' ? 'Twilio' : 'Telnyx'} is now the default for new conversations.`); this.cdr.detectChanges(); },
      error: err => { this.switching = false; this.toast.showError(this.message(err, 'Default provider could not be changed.')); this.cdr.detectChanges(); }
    });
  }
}
