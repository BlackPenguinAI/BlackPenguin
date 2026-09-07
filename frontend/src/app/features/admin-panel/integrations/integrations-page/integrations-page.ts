import { ChangeDetectorRef, Component, OnInit, isDevMode } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { HttpClient } from '@angular/common/http';
import { ToastService } from '../../../../core/services/toast';

@Component({
  selector: 'app-integrations-page',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './integrations-page.html',
  styleUrl: './integrations-page.scss',
})
export class IntegrationsPageComponent implements OnInit {
  private readonly api = `${isDevMode() ? 'http://localhost:8000' : 'https://blackpenguin.ai'}/api/v1/system`;
  config = { client_id: '', client_secret: '', client_secret_configured: false, client_secret_hint: '', redirect_uri: 'https://blackpenguin.ai/api/v1/sales/calendar/google/callback', is_enabled: false, verification_status: 'not_configured', updated_at: null as string | null };
  metaConfig = {
    app_id: '', app_secret: '', app_secret_configured: false, app_secret_hint: '', login_config_id: '',
    graph_api_version: 'v23.0', redirect_uri: 'https://blackpenguin.ai/api/v1/projects/integrations/meta/oauth/callback',
    webhook_callback_url: 'https://blackpenguin.ai/api/v1/webhooks/meta', webhook_verify_token_configured: false,
    webhook_verify_token_hint: '', requested_scopes: [] as string[], is_enabled: false,
    verification_status: 'not_configured', app_review_status: 'pending', business_verification_status: 'pending',
  };
  loading = true;
  metaLoading = true;
  saving = false;
  metaSaving = false;
  metaVerifying = false;
  dirty = false;
  metaDirty = false;
  newWebhookVerifyToken = '';

  constructor(private http: HttpClient, private toast: ToastService, private cdr: ChangeDetectorRef) {}

  ngOnInit(): void { this.load(); this.loadMeta(); }

  load(): void {
    this.http.get<any>(`${this.api}/integrations/google-calendar`).subscribe({
      next: value => {
        this.config = { ...this.config, ...value, client_secret: '' };
        this.loading = false; this.dirty = false; this.cdr.markForCheck();
      },
      error: err => { this.loading = false; this.toast.showError(err.error?.detail || 'Could not load integrations.'); this.cdr.markForCheck(); },
    });
  }

  markDirty(): void { this.dirty = true; }
  markMetaDirty(): void { this.metaDirty = true; }

  loadMeta(): void {
    this.http.get<any>(`${this.api}/integrations/meta`).subscribe({
      next: value => {
        this.metaConfig = { ...this.metaConfig, ...value, app_secret: '' };
        this.metaLoading = false; this.metaDirty = false; this.cdr.markForCheck();
      },
      error: err => { this.metaLoading = false; this.toast.showError(err.error?.detail || 'Could not load Meta integration.'); this.cdr.markForCheck(); },
    });
  }

  saveMeta(): void {
    this.metaSaving = true;
    const payload: any = {
      app_id: this.metaConfig.app_id.trim(), login_config_id: this.metaConfig.login_config_id.trim() || null,
      graph_api_version: this.metaConfig.graph_api_version.trim(), redirect_uri: this.metaConfig.redirect_uri.trim(),
      webhook_callback_url: this.metaConfig.webhook_callback_url.trim(), is_enabled: this.metaConfig.is_enabled,
      app_review_status: this.metaConfig.app_review_status, business_verification_status: this.metaConfig.business_verification_status,
    };
    if (this.metaConfig.app_secret) payload.app_secret = this.metaConfig.app_secret;
    this.http.put<any>(`${this.api}/integrations/meta`, payload).subscribe({
      next: value => {
        this.metaConfig = { ...this.metaConfig, ...value, app_secret: '' };
        this.metaSaving = false; this.metaDirty = false;
        this.toast.showSuccess('Meta platform configuration saved.'); this.cdr.markForCheck();
      },
      error: err => { this.metaSaving = false; this.toast.showError(err.error?.detail || 'Could not save Meta configuration.'); this.cdr.markForCheck(); },
    });
  }

  verifyMeta(): void {
    this.metaVerifying = true;
    this.http.post<any>(`${this.api}/integrations/meta/verify`, {}).subscribe({
      next: value => { this.metaConfig = { ...this.metaConfig, ...value, app_secret: '' }; this.metaVerifying = false; this.toast.showSuccess('Meta App credentials verified.'); this.cdr.markForCheck(); },
      error: err => { this.metaVerifying = false; this.toast.showError(err.error?.detail || 'Meta App credentials could not be verified.'); this.cdr.markForCheck(); },
    });
  }

  rotateWebhookToken(): void {
    this.http.post<any>(`${this.api}/integrations/meta/rotate-webhook-token`, {}).subscribe({
      next: value => { this.newWebhookVerifyToken = value.verify_token; this.metaConfig = { ...this.metaConfig, ...value.config, app_secret: '' }; this.toast.showSuccess('Webhook verify token rotated. Copy it to Meta now.'); this.cdr.markForCheck(); },
      error: err => this.toast.showError(err.error?.detail || 'Could not rotate the webhook token.'),
    });
  }

  save(): void {
    this.saving = true;
    const payload: any = { client_id: this.config.client_id.trim(), redirect_uri: this.config.redirect_uri.trim(), is_enabled: this.config.is_enabled };
    if (this.config.client_secret) payload.client_secret = this.config.client_secret;
    this.http.put<any>(`${this.api}/integrations/google-calendar`, payload).subscribe({
      next: value => {
        this.config = { ...this.config, ...value, client_secret: '' };
        this.saving = false; this.dirty = false;
        this.toast.showSuccess('Google Calendar platform configuration saved.'); this.cdr.markForCheck();
      },
      error: err => { this.saving = false; this.toast.showError(err.error?.detail || 'Could not save Google Calendar configuration.'); this.cdr.markForCheck(); },
    });
  }
}
