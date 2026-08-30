import { Component, OnInit, ChangeDetectorRef, isDevMode } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { HttpClient, HttpHeaders } from '@angular/common/http';
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
  
  twilioConfig = {
    account_sid: '',
    auth_token: '',
    from_phone_number: '',
    auth_token_configured: false,
    auth_token_hint: '',
    live_sms_enabled: false,
    verification_status: 'not_configured',
    verified_at: null as string | null,
    last_error: ''
  };

  isLoading: boolean = true;
  isSaving: boolean = false;
  isVerifying: boolean = false;

  constructor(
    private http: HttpClient,
    private toast: ToastService,
    private cdr: ChangeDetectorRef
  ) {}

  ngOnInit() {
    this.loadConfig();
  }

  private get baseUrl() {
    return isDevMode() ? 'http://localhost:8000' : 'https://blackpenguin.ai';
  }

  private get headers() {
    const token = localStorage.getItem('bp_token');
    return new HttpHeaders().set('Authorization', `Bearer ${token}`);
  }

  loadConfig() {
    this.isLoading = true;
    this.http.get<any>(`${this.baseUrl}/api/v1/system/messaging-settings`, { headers: this.headers }).subscribe({
      next: (data) => {
        if (data) {
          this.twilioConfig = {
            account_sid: data.account_sid || '',
            auth_token: '',
            from_phone_number: data.from_phone_number || '',
            auth_token_configured: !!data.auth_token_configured,
            auth_token_hint: data.auth_token_hint || '',
            live_sms_enabled: !!data.live_sms_enabled,
            verification_status: data.verification_status || 'not_configured',
            verified_at: data.verified_at || null,
            last_error: data.last_error || ''
          };
        }
        this.isLoading = false;
        this.cdr.detectChanges();
      },
      error: () => {
        this.toast.showError('Failed to load Twilio configuration.');
        this.isLoading = false;
        this.cdr.detectChanges();
      }
    });
  }

  saveConfig() {
    if (!this.twilioConfig.account_sid || (!this.twilioConfig.auth_token && !this.twilioConfig.auth_token_configured)) {
      this.toast.showError('Account SID and a rotated Auth Token are required.');
      return;
    }

    this.isSaving = true;
    this.cdr.detectChanges();

    const payload: any = { account_sid: this.twilioConfig.account_sid, from_phone_number: this.twilioConfig.from_phone_number, live_sms_enabled: this.twilioConfig.live_sms_enabled };
    if (this.twilioConfig.auth_token) payload.auth_token = this.twilioConfig.auth_token;
    this.http.put<any>(`${this.baseUrl}/api/v1/system/messaging-settings`, payload, { headers: this.headers }).subscribe({
      next: (data) => {
        this.twilioConfig.auth_token = '';
        this.twilioConfig.auth_token_configured = !!data.auth_token_configured;
        this.twilioConfig.auth_token_hint = data.auth_token_hint || '';
        this.twilioConfig.verification_status = data.verification_status;
        this.toast.showSuccess('Messaging settings saved successfully.');
        this.isSaving = false;
        this.cdr.detectChanges();
      },
      error: (err) => {
        this.toast.showError(err.error?.detail || 'Failed to save messaging settings.');
        this.isSaving = false;
        this.cdr.detectChanges();
      }
    });
  }

  verifyConfig() {
    this.isVerifying = true;
    this.http.post<any>(`${this.baseUrl}/api/v1/system/messaging-settings/verify`, {}, { headers: this.headers }).subscribe({
      next: data => { this.isVerifying = false; this.twilioConfig.verification_status = data.verification_status; this.twilioConfig.verified_at = data.verified_at; this.toast.showSuccess('Twilio credentials verified.'); this.cdr.detectChanges(); },
      error: err => { this.isVerifying = false; this.twilioConfig.verification_status = 'failed'; this.toast.showError(err.error?.detail || 'Twilio verification failed.'); this.cdr.detectChanges(); }
    });
  }
}
