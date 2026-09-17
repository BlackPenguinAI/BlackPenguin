import { Component, OnInit, ChangeDetectorRef, isDevMode } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { ToastService } from '../../../../core/services/toast';
import { GlassCardComponent } from '../../../../shared/ui/glass-card/glass-card';
import { InputComponent } from '../../../../shared/ui/input/input';
import { ButtonComponent } from '../../../../shared/ui/button/button';

@Component({
  selector: 'app-email-settings-page',
  standalone: true,
  imports: [CommonModule, FormsModule, GlassCardComponent, InputComponent, ButtonComponent],
  templateUrl: './email-settings-page.html'
})
export class EmailSettingsPageComponent implements OnInit {
  firebaseConfig = {
    api_key: '', auth_domain: '', project_id: '', is_enabled: false,
    auth_mode: 'rest', action_handler_url: 'https://blackpenguin.ai/activate-account',
    verification_status: 'not_configured', last_error: '',
  };
  isLoading = true;
  isSaving = false;
  isTesting = false;
  transport = { is_enabled: false, from_name: 'Black Penguin', from_email: 'info@blackpenguin.ai', reply_to: 'info@blackpenguin.ai', mail_collection: 'mail', bridge_configured: false, firebase_project_id: '', status: 'not_configured', last_error: '' };
  testRecipient = '';
  transportSaving = false;
  transportTesting = false;

  constructor(private http: HttpClient, private toast: ToastService, private cdr: ChangeDetectorRef) {}
  ngOnInit() { this.loadConfig(); this.loadTransport(); }

  private get baseUrl() { return isDevMode() ? 'http://localhost:8000' : 'https://blackpenguin.ai'; }
  private get headers() {
    return new HttpHeaders().set('Authorization', 'Bearer ' + localStorage.getItem('bp_token'));
  }

  private apiErrorMessage(error: any, fallback: string): string {
    const detail = error?.error?.detail;
    if (typeof detail === 'string' && detail.trim()) return detail;
    if (detail && typeof detail.message === 'string' && detail.message.trim()) return detail.message;
    return fallback;
  }

  loadConfig() {
    this.isLoading = true;
    this.http.get<any>(this.baseUrl + '/api/v1/system/email-settings', { headers: this.headers }).subscribe({
      next: data => {
        this.firebaseConfig = {
          api_key: data.api_key || '', auth_domain: data.auth_domain || '',
          project_id: data.project_id || '', is_enabled: !!data.is_enabled,
          auth_mode: 'rest',
          action_handler_url: data.action_handler_url || 'https://blackpenguin.ai/activate-account',
          verification_status: data.verification_status || 'not_configured',
          last_error: data.last_error || '',
        };
        this.isLoading = false; this.cdr.detectChanges();
      },
      error: () => { this.toast.showError('Failed to load Firebase configuration.'); this.isLoading = false; this.cdr.detectChanges(); }
    });
  }

  saveConfig() {
    this.isSaving = true;
    const payload: any = {
      api_key: this.firebaseConfig.api_key, auth_domain: this.firebaseConfig.auth_domain,
      project_id: this.firebaseConfig.project_id, is_enabled: this.firebaseConfig.is_enabled,
      auth_mode: this.firebaseConfig.auth_mode, action_handler_url: this.firebaseConfig.action_handler_url,
    };
    this.http.put<any>(this.baseUrl + '/api/v1/system/email-settings', payload, { headers: this.headers }).subscribe({
      next: data => {
        this.firebaseConfig.is_enabled = !!data.is_enabled;
        this.firebaseConfig.verification_status = data.verification_status;
        this.toast.showSuccess('Firebase settings saved successfully.');
        this.isSaving = false; this.cdr.detectChanges();
      },
      error: err => { this.toast.showError(this.apiErrorMessage(err, 'Failed to save Firebase settings.')); this.isSaving = false; this.cdr.detectChanges(); }
    });
  }

  testConnection() {
    this.isTesting = true;
    this.http.post<any>(this.baseUrl + '/api/v1/system/email-settings/verify', {}, { headers: this.headers }).subscribe({
      next: data => {
        this.isTesting = false; this.firebaseConfig.verification_status = data.verification_status;
        this.toast.showSuccess('Firebase REST configuration verified. You can now enable Authentication.'); this.cdr.detectChanges();
      },
      error: err => {
        this.isTesting = false; this.firebaseConfig.verification_status = 'failed';
        this.toast.showError(this.apiErrorMessage(err, 'Firebase verification failed.')); this.cdr.detectChanges();
      }
    });
  }

  loadTransport() {
    this.http.get<any>(this.baseUrl + '/api/v1/system/email-settings/appointment-transport', { headers: this.headers }).subscribe({
      next: data => { this.transport = { ...this.transport, ...data }; this.cdr.detectChanges(); },
      error: () => this.toast.showError('Failed to load appointment email transport.'),
    });
  }

  saveTransport() {
    this.transportSaving = true;
    const payload = { is_enabled: this.transport.is_enabled, from_name: this.transport.from_name, from_email: this.transport.from_email, reply_to: this.transport.reply_to, mail_collection: this.transport.mail_collection };
    this.http.put<any>(this.baseUrl + '/api/v1/system/email-settings/appointment-transport', payload, { headers: this.headers }).subscribe({
      next: data => { this.transport = { ...this.transport, ...data }; this.transportSaving = false; this.toast.showSuccess('Appointment email transport saved.'); this.cdr.detectChanges(); },
      error: err => { this.transportSaving = false; this.toast.showError(this.apiErrorMessage(err, 'Appointment email transport could not be saved.')); this.cdr.detectChanges(); },
    });
  }

  testTransport() {
    if (!this.testRecipient) return;
    this.transportTesting = true;
    this.http.post<any>(this.baseUrl + '/api/v1/system/email-settings/appointment-transport/verify', { test_recipient: this.testRecipient }, { headers: this.headers }).subscribe({
      next: data => { this.transport = { ...this.transport, ...data }; this.transportTesting = false; this.toast.showSuccess('Test email queued in Firestore.'); this.cdr.detectChanges(); },
      error: err => { this.transportTesting = false; this.toast.showError(this.apiErrorMessage(err, 'Test email could not be queued.')); this.cdr.detectChanges(); },
    });
  }

}
