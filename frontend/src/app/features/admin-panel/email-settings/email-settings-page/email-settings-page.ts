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
    api_key: '', auth_domain: '', project_id: '', credentials_json: '',
    credentials_configured: false, credentials_hint: '', is_enabled: false,
    auth_mode: 'hybrid', action_handler_url: 'https://blackpenguin.ai/activate-account',
    verification_status: 'not_configured', last_error: '',
  };
  isLoading = true;
  isSaving = false;
  isTesting = false;

  constructor(private http: HttpClient, private toast: ToastService, private cdr: ChangeDetectorRef) {}
  ngOnInit() { this.loadConfig(); }

  private get baseUrl() { return isDevMode() ? 'http://localhost:8000' : 'https://blackpenguin.ai'; }
  private get headers() {
    return new HttpHeaders().set('Authorization', 'Bearer ' + localStorage.getItem('bp_token'));
  }

  loadConfig() {
    this.isLoading = true;
    this.http.get<any>(this.baseUrl + '/api/v1/system/email-settings', { headers: this.headers }).subscribe({
      next: data => {
        this.firebaseConfig = {
          api_key: data.api_key || '', auth_domain: data.auth_domain || '',
          project_id: data.project_id || '', credentials_json: '',
          credentials_configured: !!data.credentials_configured,
          credentials_hint: data.credentials_hint || '', is_enabled: !!data.is_enabled,
          auth_mode: data.auth_mode || 'hybrid',
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
    if (this.firebaseConfig.credentials_json) payload.credentials_json = this.firebaseConfig.credentials_json;
    this.http.put<any>(this.baseUrl + '/api/v1/system/email-settings', payload, { headers: this.headers }).subscribe({
      next: data => {
        this.firebaseConfig.credentials_json = '';
        this.firebaseConfig.credentials_configured = !!data.credentials_configured;
        this.firebaseConfig.credentials_hint = data.credentials_hint || '';
        this.firebaseConfig.verification_status = data.verification_status;
        this.toast.showSuccess('Firebase settings saved successfully.');
        this.isSaving = false; this.cdr.detectChanges();
      },
      error: err => { this.toast.showError(err.error?.detail || 'Failed to save Firebase settings.'); this.isSaving = false; this.cdr.detectChanges(); }
    });
  }

  testConnection() {
    this.isTesting = true;
    this.http.post<any>(this.baseUrl + '/api/v1/system/email-settings/verify', {}, { headers: this.headers }).subscribe({
      next: data => {
        this.isTesting = false; this.firebaseConfig.verification_status = data.verification_status;
        this.firebaseConfig.credentials_configured = !!data.credentials_configured;
        this.firebaseConfig.credentials_hint = data.credentials_hint || '';
        this.toast.showSuccess('Firebase Authentication verified.'); this.cdr.detectChanges();
      },
      error: err => {
        this.isTesting = false; this.firebaseConfig.verification_status = 'failed';
        this.toast.showError(err.error?.detail || 'Firebase verification failed.'); this.cdr.detectChanges();
      }
    });
  }

  onFileSelected(event: any) {
    const file = event.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = e => {
      try {
        const parsed = JSON.parse(e.target?.result as string);
        this.firebaseConfig.credentials_json = JSON.stringify(parsed, null, 2);
        if (parsed.project_id) this.firebaseConfig.project_id = parsed.project_id;
        this.toast.showSuccess('Service Account JSON loaded successfully.');
      } catch {
        this.toast.showError('Invalid JSON file. Please check the file structure.');
      }
      event.target.value = ''; this.cdr.detectChanges();
    };
    reader.readAsText(file);
  }

  formatJson() {
    if (!this.firebaseConfig.credentials_json) return;
    try {
      const parsed = JSON.parse(this.firebaseConfig.credentials_json);
      this.firebaseConfig.credentials_json = JSON.stringify(parsed, null, 2);
      if (parsed.project_id && !this.firebaseConfig.project_id) this.firebaseConfig.project_id = parsed.project_id;
    } catch {}
  }
}
