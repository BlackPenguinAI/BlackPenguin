import { Component, OnInit, isDevMode, ChangeDetectorRef } from '@angular/core'; // 🚀 Importado ChangeDetectorRef
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { TranslateModule, TranslateService } from '@ngx-translate/core';

@Component({
  selector: 'app-staff-ai-config',
  standalone: true,
  imports: [CommonModule, FormsModule, TranslateModule],
  templateUrl: './ai-config.html'
})
export class StaffAiConfigComponent implements OnInit {
  
  config = {
    available_models: [] as string[],
    agent_onboarding_empresa: { model: '', system_prompt: '', protocol_prompt: '', guardrails_prompt: '' },
    agent_onboarding_proyectos: { model: '', system_prompt: '', protocol_prompt: '', guardrails_prompt: '' },
    agent_ventas: { model: '', system_prompt: '', protocol_prompt: '', guardrails_prompt: '' },
    agent_reporteria: { model: '', system_prompt: '', protocol_prompt: '', guardrails_prompt: '' }
  };
  
  activeTab: string = 'empresa';
  isSaving: boolean = false;
  statusMessage: string = '';
  isError: boolean = false;

  constructor(
    private http: HttpClient, 
    private translate: TranslateService,
    private cdr: ChangeDetectorRef // 🚀 Inyectamos el control de renderizado
  ) {}

  private getUrl() {
    return isDevMode() 
      ? 'http://localhost:8000/api/v1/conversations/config' 
      : 'https://blackpenguin.ai/api/v1/conversations/config'; 
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
        this.cdr.detectChanges(); // 🚀 Obligamos a pintar los prompts cuando llegan del backend
      },
      error: (err) => {
        console.error('Error cargando la configuración de los agentes:', err);
        this.cdr.detectChanges();
      }
    });
  }

  setTab(tab: string) { 
    this.activeTab = tab; 
    this.cdr.detectChanges(); // 🚀 Magia pura: La pestaña cambia instantáneamente sin doble clic
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

  onSave() {
    this.isSaving = true;
    this.statusMessage = '';
    this.isError = false;
    this.cdr.detectChanges(); // 🚀 Mostramos el botón de "Guardando..." en el acto

    this.http.put(this.getUrl(), this.config, { headers: this.getHeaders() }).subscribe({
      next: () => {
        this.isSaving = false;
        this.isError = false;
        this.statusMessage = 'Configuración IA actualizada en el ecosistema.';
        this.cdr.detectChanges(); // 🚀 Mostramos el mensaje de éxito de inmediato
        
        setTimeout(() => {
          this.statusMessage = '';
          this.cdr.detectChanges(); // 🚀 Ocultamos el mensaje con suavidad
        }, 4000);
      },
      error: (err) => {
        this.isSaving = false;
        this.isError = true;
        this.statusMessage = err.error?.detail || 'Error actualizando configuración.';
        this.cdr.detectChanges(); // 🚀 Mostramos el error si el backend falla
      }
    });
  }
}