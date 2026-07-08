import { Component, OnInit, isDevMode } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { TranslateModule, TranslateService } from '@ngx-translate/core';

@Component({
  selector: 'app-staff-ai-config',
  standalone: true,
  imports: [CommonModule, FormsModule, TranslateModule],
  templateUrl: './ai-config.html',
  styleUrl: './ai-config.scss'
})
export class StaffAiConfigComponent implements OnInit {
  
  // 🚀 Estructura base de los 4 Agentes
  config = {
    openrouter_api_key: '',
    available_models: [] as string[],
    agent_onboarding_empresa: { model: '', system_prompt: '', protocol_prompt: '', guardrails_prompt: '' },
    agent_onboarding_proyectos: { model: '', system_prompt: '', protocol_prompt: '', guardrails_prompt: '' },
    agent_ventas: { model: '', system_prompt: '', protocol_prompt: '', guardrails_prompt: '' },
    agent_reporteria: { model: '', system_prompt: '', protocol_prompt: '', guardrails_prompt: '' }
  };
  
  newModelName: string = '';
  activeTab: string = 'empresa'; // 'empresa' | 'proyectos' | 'ventas' | 'reporteria'
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
    // 1. Cargar la Configuración
    this.http.get<any>(this.getUrl(), { headers: this.getHeaders() }).subscribe({
      next: (data) => {
        if (data) this.config = { ...this.config, ...data };
        this.checkConsumption(); // 2. Comprobar créditos
      }
    });
  }

  // --- COMPROBAR CONSUMO OPENROUTER ---
  checkConsumption() {
    if (!this.config.openrouter_api_key) return;
    this.http.get<any>(this.getUrl('/consumption'), { headers: this.getHeaders() }).subscribe({
      next: (res) => this.consumption = res
    });
  }

  // --- CRUD DE MODELOS ---
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

  // --- CAMBIO DE PESTAÑAS ---
  setTab(tab: string) {
    this.activeTab = tab;
  }

  get activeAgent() {
    switch(this.activeTab) {
      case 'empresa': return this.config.agent_onboarding_empresa;
      case 'proyectos': return this.config.agent_onboarding_proyectos;
      case 'ventas': return this.config.agent_ventas;
      case 'reporteria': return this.config.agent_reporteria;
      default: return this.config.agent_onboarding_empresa;
    }
  }

  // --- GUARDADO ---
  onSave() {
    this.isSaving = true;
    this.statusMessage = '';
    
    this.http.put(this.getUrl(), this.config, { headers: this.getHeaders() }).subscribe({
      next: () => {
        this.isSaving = false;
        this.isError = false;
        this.statusMessage = this.translate.instant('AI_CONFIG.MSG_SUCCESS') || '🧠 ¡Actualizado con éxito!';
        this.checkConsumption();
        setTimeout(() => this.statusMessage = '', 4000);
      },
      error: () => {
        this.isSaving = false;
        this.isError = true;
        this.statusMessage = this.translate.instant('AI_CONFIG.MSG_ERROR') || 'Error crítico al salvar.';
      }
    });
  }
}