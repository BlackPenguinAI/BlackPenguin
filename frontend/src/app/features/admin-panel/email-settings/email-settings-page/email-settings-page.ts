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
    api_key: '',
    auth_domain: '',
    project_id: '',
    credentials_json: ''
  };

  isLoading: boolean = true;
  isSaving: boolean = false;

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
    this.http.get<any>(`${this.baseUrl}/api/v1/system/email-settings`, { headers: this.headers }).subscribe({
      next: (data) => {
        if (data) {
          this.firebaseConfig = {
            api_key: data.api_key || '',
            auth_domain: data.auth_domain || '',
            project_id: data.project_id || '',
            credentials_json: data.credentials_json || ''
          };
          this.formatJson(); // Intenta embellecer el JSON si ya existe
        }
        this.isLoading = false;
        this.cdr.detectChanges();
      },
      error: () => {
        this.toast.showError('Failed to load Firebase configuration.');
        this.isLoading = false;
        this.cdr.detectChanges();
      }
    });
  }

  saveConfig() {
    this.isSaving = true;
    this.cdr.detectChanges();

    this.http.put<any>(`${this.baseUrl}/api/v1/system/email-settings`, this.firebaseConfig, { headers: this.headers }).subscribe({
      next: () => {
        this.toast.showSuccess('Firebase settings saved successfully.');
        this.isSaving = false;
        this.cdr.detectChanges();
      },
      error: (err) => {
        this.toast.showError(err.error?.detail || 'Failed to save Firebase settings.');
        this.isSaving = false;
        this.cdr.detectChanges();
      }
    });
  }

  // 🚀 LECTURA DEL ARCHIVO JSON
  onFileSelected(event: any) {
    const file = event.target.files[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = (e) => {
      try {
        const result = e.target?.result as string;
        const parsedJson = JSON.parse(result); // Validamos que sea un JSON real
        
        // Lo asignamos al text area formateado
        this.firebaseConfig.credentials_json = JSON.stringify(parsedJson, null, 2);
        
        // Autocompletar el Project ID si viene en el JSON
        if (parsedJson.project_id) {
          this.firebaseConfig.project_id = parsedJson.project_id;
        }

        this.toast.showSuccess('Service Account JSON loaded successfully.');
        this.cdr.detectChanges();

      } catch (err) {
        this.toast.showError('Invalid JSON file. Please check the file structure.');
      }
      
      // Limpiar el input para permitir cargar el mismo archivo si es necesario
      event.target.value = '';
    };
    reader.readAsText(file);
  }

  // 🚀 FORMATEAR JSON MANUAL
  formatJson() {
    if (!this.firebaseConfig.credentials_json) return;
    try {
      const parsed = JSON.parse(this.firebaseConfig.credentials_json);
      this.firebaseConfig.credentials_json = JSON.stringify(parsed, null, 2);
      
      if (parsed.project_id && !this.firebaseConfig.project_id) {
        this.firebaseConfig.project_id = parsed.project_id;
      }
    } catch (err) {
      // Si el usuario está tipeando y se equivoca, no formateamos para no borrarle nada
    }
  }
}