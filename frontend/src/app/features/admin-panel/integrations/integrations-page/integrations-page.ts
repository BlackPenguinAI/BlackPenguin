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
  loading = true;
  saving = false;
  dirty = false;

  constructor(private http: HttpClient, private toast: ToastService, private cdr: ChangeDetectorRef) {}

  ngOnInit(): void { this.load(); }

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
