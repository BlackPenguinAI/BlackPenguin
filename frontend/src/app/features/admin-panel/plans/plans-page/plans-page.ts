import { Component, OnInit, ChangeDetectorRef } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { TranslateModule, TranslateService } from '@ngx-translate/core';

import { PlanService } from '../services/plan';
import { ToastService } from '../../../../core/services/toast';

import { GlassCardComponent } from '../../../../shared/ui/glass-card/glass-card';
import { InputComponent } from '../../../../shared/ui/input/input';
import { ButtonComponent } from '../../../../shared/ui/button/button';
import { ModalComponent } from '../../../../shared/ui/modal/modal';

@Component({
  selector: 'app-plans-page',
  standalone: true,
  imports: [
    CommonModule, 
    FormsModule, 
    TranslateModule,
    GlassCardComponent,
    InputComponent,
    ButtonComponent,
    ModalComponent
  ],
  templateUrl: './plans-page.html'
})
export class PlansPageComponent implements OnInit {
  plans: any[] = [];
  
  isLoading: boolean = true;
  isSaving: boolean = false;
  isDeleting: boolean = false;
  
  showModal: boolean = false;
  showEditModal: boolean = false;
  showDeleteModal: boolean = false;
  planToDeleteId: string | null = null;

  form: any = {
    name: '',
    description: '',
    max_assistants: 0,
    max_mkt_users: 0,
    max_sales_users: 0,
    max_projects: 1,
    max_properties_per_project: 50,
    is_active: true
  };

  editForm: any = {
    id: '',
    name: '',
    description: '',
    max_assistants: 0,
    max_mkt_users: 0,
    max_sales_users: 0,
    max_projects: 1,
    max_properties_per_project: 50,
    is_active: true
  };

  constructor(
    private planService: PlanService,
    private toast: ToastService,
    private cdr: ChangeDetectorRef,
    private translate: TranslateService
  ) {}

  ngOnInit(): void {
    this.loadPlans();
  }

  loadPlans(): void {
    this.isLoading = true;
    this.planService.getPlans().subscribe({
      next: (data) => {
        this.plans = data;
        this.isLoading = false;
        this.cdr.detectChanges();
      },
      error: () => {
        this.toast.showError('Failed to load plans.');
        this.isLoading = false;
        this.cdr.detectChanges();
      }
    });
  }

  openModal(): void {
    this.form = { name: '', description: '', max_assistants: 0, max_mkt_users: 0, max_sales_users: 0, max_projects: 1, max_properties_per_project: 50, is_active: true };
    this.showModal = true;
  }

  closeModal(): void {
    this.showModal = false;
  }

  openEditModal(plan: any): void {
    this.editForm = { ...plan };
    this.showEditModal = true;
  }

  closeEditModal(): void {
    this.showEditModal = false;
  }

  openDeleteModal(id: string): void {
    this.planToDeleteId = id;
    this.showDeleteModal = true;
  }

  closeDeleteModal(): void {
    this.showDeleteModal = false;
    this.planToDeleteId = null;
  }

  savePlan(): void {
    if (!this.form.name) {
      this.toast.showError('Plan name is required.');
      return;
    }

    this.isSaving = true;
    this.planService.createPlan(this.form).subscribe({
      next: () => {
        this.isSaving = false;
        this.closeModal();
        this.loadPlans();
        this.toast.showSuccess('Plan created successfully.');
      },
      error: (err) => {
        this.isSaving = false;
        this.toast.showError(err.error?.detail || 'Failed to create plan.');
      }
    });
  }

  updatePlan(): void {
    if (!this.editForm.name) {
      this.toast.showError('Plan name is required.');
      return;
    }

    this.isSaving = true;
    this.planService.updatePlan(this.editForm.id, this.editForm).subscribe({
      next: () => {
        this.isSaving = false;
        this.closeEditModal();
        this.loadPlans();
        this.toast.showSuccess('Plan updated successfully.');
      },
      error: (err) => {
        this.isSaving = false;
        this.toast.showError(err.error?.detail || 'Failed to update plan.');
      }
    });
  }

  confirmDelete(): void {
    if (!this.planToDeleteId) return;
    
    this.isDeleting = true;
    this.planService.deletePlan(this.planToDeleteId).subscribe({
      next: () => {
        this.isDeleting = false;
        this.closeDeleteModal();
        this.loadPlans();
        this.toast.showSuccess('Plan deleted successfully.');
      },
      error: (err) => {
        this.isDeleting = false;
        this.closeDeleteModal();
        this.toast.showError(err.error?.detail || 'Failed to delete plan.');
      }
    });
  }
}
