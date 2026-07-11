import { Component, OnInit, isDevMode } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { TranslateModule, TranslateService } from '@ngx-translate/core';

@Component({
  selector: 'app-staff-ai-keys',
  standalone: true,
  imports: [CommonModule, FormsModule, TranslateModule],
  templateUrl: './ai-keys.html'
})
export class StaffAiKeysComponent implements OnInit {
  
  config: any = { openrouter_api_key: '', available_models: [] };
  newModelName: string = '';
  consumption: { usage: number, limit: number | null, error?: string } = { usage: 0, limit: 0 };
  
  isSaving: boolean = false;
  statusMessage: string = '';
  isError: boolean = false;

  constructor(private http: HttpClient, private translate: TranslateService) {}

  private getUrl(endpoint: string = '') {
    const base = isDevMode() ? 'http://localhost:8000/api/v1' : 'https://blackpenguin.ai/api/v1';
    return `${base}/conversations/config${endpoint}`; 
  }

  private getHeaders() {
    const token = localStorage.getItem('bp_token');
    return new HttpHeaders().set('Authorization', `Bearer ${token}`);
  }

  ngOnInit() {
    this.http.get<any>(this.getUrl(), { headers: this.getHeaders() }).subscribe({
      next: (data) => {
        if (data) this.config = { ...this.config, ...data };
        this.checkConsumption();
      }
    });
  }

  checkConsumption() {
    if (!this.config.openrouter_api_key) return;
    this.http.get<any>(this.getUrl('/consumption'), { headers: this.getHeaders() }).subscribe({
      next: (res) => this.consumption = res
    });
  }

  addModel() {
    const m = this.newModelName.trim().toLowerCase();
    if (m && !this.config.available_models.includes(m)) {
      this.config.available_models.push(m);
      this.newModelName = '';
    }
  }

  removeModel(index: number) {
    this.config.available_models.splice(index, 1);
  }

  onSave() {
    this.isSaving = true;
    this.statusMessage = '';
    
    this.http.put(this.getUrl(), this.config, { headers: this.getHeaders() }).subscribe({
      next: () => {
        this.isSaving = false;
        this.isError = false;
        this.statusMessage = 'Infraestructura guardada con éxito.';
        this.checkConsumption();
        setTimeout(() => this.statusMessage = '', 4000);
      },
      error: () => {
        this.isSaving = false;
        this.isError = true;
        this.statusMessage = 'Error al guardar.';
      }
    });
  }
}