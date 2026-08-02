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
    from_phone_number: ''
  };

  isLoading: boolean = true;
  isSaving: boolean = false;
  showToken: boolean = false; // Alterna la visibilidad del token

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
            auth_token: data.auth_token || '',
            from_phone_number: data.from_phone_number || ''
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
    if (!this.twilioConfig.account_sid || !this.twilioConfig.auth_token) {
      this.toast.showError('Account SID and Auth Token are required.');
      return;
    }

    this.isSaving = true;
    this.cdr.detectChanges();

    this.http.put<any>(`${this.baseUrl}/api/v1/system/messaging-settings`, this.twilioConfig, { headers: this.headers }).subscribe({
      next: () => {
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

  toggleTokenVisibility() {
    this.showToken = !this.showToken;
  }
}