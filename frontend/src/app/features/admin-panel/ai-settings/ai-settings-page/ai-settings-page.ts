import { Component, OnInit, ChangeDetectorRef } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { TranslateModule } from '@ngx-translate/core';

import { AiConfigService } from './../services/ai-config';
import { ToastService } from '../../../../core/services/toast';

import { GlassCardComponent } from '../../../../shared/ui/glass-card/glass-card';
import { ButtonComponent } from '../../../../shared/ui/button/button';

@Component({
  selector: 'app-ai-settings-page',
  standalone: true,
  imports: [CommonModule, FormsModule, TranslateModule, GlassCardComponent, ButtonComponent],
  templateUrl: './ai-settings-page.html'
})
export class AiSettingsPageComponent implements OnInit {
  
  config: any = {
    available_models: [],
    agent_onboarding_empresa: { model: '', system_prompt: '', protocol_prompt: '', guardrails_prompt: '' },
    agent_onboarding_proyectos: { model: '', system_prompt: '', protocol_prompt: '', guardrails_prompt: '' },
    agent_ventas: { model: '', system_prompt: '', protocol_prompt: '', guardrails_prompt: '' },
    agent_reporteria: { model: '', system_prompt: '', protocol_prompt: '', guardrails_prompt: '' }
  };
  
  activeTab: string = 'empresa';
  isLoading: boolean = true;
  isSaving: boolean = false;

  constructor(
    private aiService: AiConfigService, 
    private toast: ToastService,
    private cdr: ChangeDetectorRef
  ) {}

  ngOnInit() {
    this.loadConfig();
  }

  loadConfig() {
    this.aiService.getConfig().subscribe({
      next: (data) => {
        this.config = data;
        this.isLoading = false;
        this.cdr.detectChanges();
      },
      error: () => {
        this.toast.showError('Error al cargar la configuración de los agentes.');
        this.isLoading = false;
        this.cdr.detectChanges();
      }
    });
  }

  setTab(tab: string) { 
    this.activeTab = tab; 
    this.cdr.detectChanges(); 
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

  saveSettings() {
    this.isSaving = true;
    this.cdr.detectChanges();

    this.aiService.updateConfig(this.config).subscribe({
      next: () => {
        this.isSaving = false;
        this.toast.showSuccess('Configuración de Agentes actualizada en el ecosistema.');
        this.cdr.detectChanges(); 
      },
      error: (err) => {
        this.isSaving = false;
        this.toast.showError(err.error?.detail || 'Error al guardar los prompts.');
        this.cdr.detectChanges();
      }
    });
  }
}