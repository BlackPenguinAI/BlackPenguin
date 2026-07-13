import { Component, OnInit, isDevMode, ChangeDetectorRef } from '@angular/core'; // 🚀 Añadido ChangeDetectorRef
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

  constructor(
    private http: HttpClient, 
    private translate: TranslateService,
    private cdr: ChangeDetectorRef // 🚀 Control nativo de renderizado inyectado
  ) {}

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
        if (data) {
          this.config = { ...this.config, ...data };
        }
        this.cdr.detectChanges(); // 🚀 Obligamos a pintar la info que llegó del servidor en el acto
        this.checkConsumption();
      },
      error: (err) => {
        console.error('Error cargando las credenciales AI', err);
        this.cdr.detectChanges();
      }
    });
  }

  checkConsumption() {
    if (!this.config.openrouter_api_key) return;
    this.http.get<any>(this.getUrl('/consumption'), { headers: this.getHeaders() }).subscribe({
      next: (res) => {
        this.consumption = res;
        this.cdr.detectChanges(); // 🚀 Actualizamos el uso mensual de la API al instante
      },
      error: (err) => {
        console.error('Error consultando consumo de la API', err);
        this.cdr.detectChanges();
      }
    });
  }

  addModel() {
    const m = this.newModelName.trim().toLowerCase();
    if (m && !this.config.available_models.includes(m)) {
      this.config.available_models.push(m);
      this.newModelName = '';
      this.cdr.detectChanges(); // 🚀 Refrescamos la lista de modelos de forma síncrona
    }
  }

  removeModel(index: number) {
    this.config.available_models.splice(index, 1);
    this.cdr.detectChanges(); // 🚀 Refrescamos la lista al eliminar un modelo
  }

  onSave() {
    this.isSaving = true;
    this.statusMessage = '';
    this.cdr.detectChanges(); // 🚀 Mostramos visualmente que está "Guardando..."
    
    this.http.put(this.getUrl(), this.config, { headers: this.getHeaders() }).subscribe({
      next: () => {
        this.isSaving = false;
        this.isError = false;
        this.statusMessage = 'Infraestructura guardada correctamente.';
        this.cdr.detectChanges(); // 🚀 Mostramos mensaje de éxito
        
        setTimeout(() => {
          this.statusMessage = '';
          this.cdr.detectChanges(); // 🚀 Limpiamos el mensaje de éxito de forma limpia
        }, 4000);
      },
      error: (err) => {
        this.isSaving = false;
        this.isError = true;
        this.statusMessage = err.error?.detail || 'Error al guardar la infraestructura.';
        this.cdr.detectChanges(); // 🚀 Mostramos el error si el backend falla
      }
    });
  }
}