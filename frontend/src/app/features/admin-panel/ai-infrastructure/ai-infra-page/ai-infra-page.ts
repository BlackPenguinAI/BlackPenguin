import { Component, OnInit, ChangeDetectorRef } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { TranslateModule } from '@ngx-translate/core';

import { AiConfigService } from '../../ai-settings/services/ai-config';
import { ToastService } from '../../../../core/services/toast';

// Componentes Atómicos
import { GlassCardComponent } from '../../../../shared/ui/glass-card/glass-card';
import { InputComponent } from '../../../../shared/ui/input/input';
import { ButtonComponent } from '../../../../shared/ui/button/button';

@Component({
  selector: 'app-ai-infra-page',
  standalone: true,
  imports: [CommonModule, FormsModule, TranslateModule, GlassCardComponent, InputComponent, ButtonComponent],
  templateUrl: './ai-infra-page.html'
})
export class AiInfraPageComponent implements OnInit {
  config: any = { openrouter_api_key: '', available_models: [] };
  newModelName: string = '';
  consumption: { usage: number, limit: number | null, error?: string } = { usage: 0, limit: 0 };
  
  isLoading: boolean = true;
  isSaving: boolean = false;

  constructor(
    private aiService: AiConfigService, 
    private toast: ToastService,
    private cdr: ChangeDetectorRef
  ) {}

  ngOnInit() {
    this.loadData();
  }

  loadData() {
    this.isLoading = true;
    this.aiService.getConfig().subscribe({
      next: (data) => {
        this.config = data;
        this.loadConsumption();
      },
      error: () => {
        this.toast.showError('Error al cargar configuración de IA.');
        this.isLoading = false;
        this.cdr.detectChanges();
      }
    });
  }

  loadConsumption() {
    this.aiService.getConsumption().subscribe({
      next: (data) => {
        this.consumption = data;
        this.isLoading = false;
        this.cdr.detectChanges();
      },
      error: () => {
        this.isLoading = false;
        this.cdr.detectChanges();
      }
    });
  }

  addModel() {
    const m = this.newModelName.trim().toLowerCase();
    if (m && !this.config.available_models.includes(m)) {
      this.config.available_models.push(m);
      this.newModelName = '';
      this.cdr.detectChanges();
    }
  }

  removeModel(index: number) {
    this.config.available_models.splice(index, 1);
    this.cdr.detectChanges();
  }

  saveConfig() {
    this.isSaving = true;
    this.cdr.detectChanges();
    
    this.aiService.updateConfig(this.config).subscribe({
      next: () => {
        this.isSaving = false;
        this.toast.showSuccess('Infraestructura guardada correctamente.');
        this.cdr.detectChanges();
      },
      error: (err) => {
        this.isSaving = false;
        this.toast.showError(err.error?.detail || 'Error al guardar la infraestructura.');
        this.cdr.detectChanges();
      }
    });
  }
}