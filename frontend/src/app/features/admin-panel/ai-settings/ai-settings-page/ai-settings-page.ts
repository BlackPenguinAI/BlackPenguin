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
    agent_ventas: { model: '', system_prompt: '', protocol_prompt: '', guardrails_prompt: '', stage_prompts: {}, segment_prompts: {}, objection_prompts: {}, sms_templates: {}, scoring_config: {}, cadence_config: {} },
    agent_reporteria: { model: '', system_prompt: '', protocol_prompt: '', guardrails_prompt: '' }
  };
  
  activeTab: string = 'empresa';
  isLoading: boolean = true;
  isSaving: boolean = false;
  promptVersions: any[] = [];
  promptVersionsLoaded = false;
  promptVersionsLoading = false;
  promptVersionsError = '';
  promptVersionsPage = 1;
  promptVersionsTotal = 0;
  readonly promptVersionsPageSize = 20;
  stagePromptKeys: string[] = [];
  segmentPromptKeys: string[] = [];
  restoringVersionId = '';
  changeNote = '';

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
        this.refreshPromptKeys();
        if (this.activeTab === 'ventas' && this.promptVersionsLoaded) {
          this.loadPromptVersions(this.promptVersionsPage);
        }
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

  loadPromptVersions(page = 1) {
    this.promptVersionsLoading = true;
    this.promptVersionsError = '';
    this.aiService.getSalesPromptVersions(page, this.promptVersionsPageSize).subscribe({
      next: response => {
        this.promptVersions = response.items || [];
        this.promptVersionsPage = response.page || page;
        this.promptVersionsTotal = response.total || 0;
        this.promptVersionsLoaded = true;
        this.promptVersionsLoading = false;
        this.cdr.detectChanges();
      },
      error: err => {
        this.promptVersionsLoading = false;
        this.promptVersionsLoaded = true;
        this.promptVersionsError = err.error?.detail || 'Prompt history could not be loaded.';
        this.cdr.detectChanges();
      },
    });
  }

  restorePromptVersion(version: any) {
    this.restoringVersionId = version.id;
    this.aiService.restoreSalesPromptVersion(version.id).subscribe({
      next: () => {
        this.restoringVersionId = '';
        this.toast.showSuccess(`Versión ${version.version} restaurada como una nueva versión publicada.`);
        this.loadConfig();
      },
      error: (err) => {
        this.restoringVersionId = '';
        this.toast.showError(err.error?.detail || 'No se pudo restaurar la versión.');
      }
    });
  }

  publishVersion(version: any): void {
    this.restoringVersionId = version.id;
    this.aiService.publishSalesPromptVersion(version.id).subscribe({
      next: () => { this.restoringVersionId = ''; this.toast.showSuccess(`Version ${version.version} published.`); this.loadConfig(); },
      error: err => { this.restoringVersionId = ''; this.toast.showError(err.error?.detail || 'The version could not be published.'); },
    });
  }

  loadVersion(version: any): void {
    this.restoringVersionId = version.id;
    this.aiService.getSalesPromptVersion(version.id).subscribe({
      next: detail => {
        this.config.agent_ventas = JSON.parse(JSON.stringify(detail.configuration));
        this.refreshPromptKeys();
        this.restoringVersionId = '';
        this.changeNote = `Based on version ${version.version}`;
        this.toast.showSuccess(`Version ${version.version} loaded into the editor. Publishing will create an auditable change.`);
        this.cdr.detectChanges();
      },
      error: err => {
        this.restoringVersionId = '';
        this.toast.showError(err.error?.detail || 'The prompt version could not be loaded.');
        this.cdr.detectChanges();
      },
    });
  }

  setTab(tab: string) {
    this.activeTab = tab;
    if (tab === 'ventas' && !this.promptVersionsLoaded && !this.promptVersionsLoading) {
      this.loadPromptVersions();
    }
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
    if (this.activeTab === 'ventas') {
      this.saveSalesDraft(false);
      return;
    }
    this.isSaving = true;
    this.cdr.detectChanges();

    const key = ({ empresa: 'agent_onboarding_empresa', proyectos: 'agent_onboarding_proyectos', reporteria: 'agent_reporteria' } as Record<string, string>)[this.activeTab];
    const payload = { available_models: this.config.available_models, [key]: this.activeAgent };
    this.aiService.updateConfig(payload).subscribe({
      next: () => {
        this.isSaving = false;
        this.toast.showSuccess('Configuración de Agentes actualizada en el ecosistema.');
        if (this.promptVersionsLoaded) this.loadPromptVersions(this.promptVersionsPage);
        this.cdr.detectChanges(); 
      },
      error: (err) => {
        this.isSaving = false;
        this.toast.showError(err.error?.detail || 'Error al guardar los prompts.');
        this.cdr.detectChanges();
      }
    });
  }

  saveSalesDraft(publish: boolean): void {
    this.isSaving = true;
    this.aiService.createSalesPromptDraft(this.config.agent_ventas, this.changeNote).subscribe({
      next: version => {
        if (!publish) {
          this.isSaving = false; this.changeNote = ''; this.toast.showSuccess(`Draft version ${version.version} saved.`); this.loadPromptVersions(); this.cdr.detectChanges();
          return;
        }
        this.aiService.publishSalesPromptVersion(version.id).subscribe({
          next: () => { this.isSaving = false; this.changeNote = ''; this.toast.showSuccess(`Version ${version.version} published.`); this.loadConfig(); },
          error: err => { this.isSaving = false; this.toast.showError(err.error?.detail || 'The draft could not be published.'); this.cdr.detectChanges(); },
        });
      },
      error: err => { this.isSaving = false; this.toast.showError(err.error?.detail || 'The prompt draft could not be saved.'); this.cdr.detectChanges(); },
    });
  }

  trackByKey(_index: number, key: string): string { return key; }

  get hasPreviousPromptPage(): boolean { return this.promptVersionsPage > 1; }
  get hasNextPromptPage(): boolean {
    return this.promptVersionsPage * this.promptVersionsPageSize < this.promptVersionsTotal;
  }

  private refreshPromptKeys(): void {
    this.stagePromptKeys = Object.keys(this.config.agent_ventas?.stage_prompts || {});
    this.segmentPromptKeys = Object.keys(this.config.agent_ventas?.segment_prompts || {});
  }
}
