import { Component, OnInit, ChangeDetectorRef } from '@angular/core'; 
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { TranslateModule, TranslateService } from '@ngx-translate/core';

import { PlanService } from './../services/plan';
import { ToastService } from '../../../../core/services/toast';

// 🚀 IMPORTAMOS LOS COMPONENTES ATÓMICOS
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
  
  showModal: boolean = false;
  
  showDeleteModal: boolean = false;
  planToDelete: string | null = null;
  isDeleting: boolean = false;

  form: any = {
    name: '',
    description: '',
    max_admins: 1,
    max_mkt_users: 0,
    max_sales_users: 0,
    max_projects: 1,
    max_properties_per_project: 50,
    is_active: true
  };

  constructor(
    private planService: PlanService,
    private translate: TranslateService,
    private toast: ToastService,
    private cdr: ChangeDetectorRef
  ) {}

  ngOnInit(): void {
    this.loadPlans();
  }

  loadPlans() {
    this.isLoading = true;
    this.planService.getPlans().subscribe({
      next: (data) => {
        this.plans = data;
        this.isLoading = false;
        this.cdr.detectChanges();
      },
      error: () => {
        this.toast.showError('Error al cargar los planes.');
        this.isLoading = false;
        this.cdr.detectChanges();
      }
    });
  }

  openModal() {
    this.form = {
      name: '', description: '', max_admins: 1, max_mkt_users: 0,
      max_sales_users: 0, max_projects: 1, max_properties_per_project: 50, is_active: true
    };
    this.showModal = true;
    this.cdr.detectChanges();
  }

  closeModal() {
    this.showModal = false;
    this.cdr.detectChanges();
  }

  savePlan() {
    if (!this.form.name) {
      this.toast.showError('El nombre del plan es obligatorio.');
      return;
    }
    
    this.isSaving = true;
    this.cdr.detectChanges();

    this.planService.createPlan(this.form).subscribe({
      next: () => {
        this.isSaving = false;
        this.closeModal();
        this.loadPlans();
        this.toast.showSuccess(this.translate.instant('PLANS_PAGE.MSG_CREATE_SUCCESS') || 'Plan creado con éxito.');
      },
      error: (err) => {
        this.isSaving = false;
        this.cdr.detectChanges(); 
        this.toast.showError(err.error?.detail || 'Error al crear el plan.'); 
      }
    });
  }

  openDeleteModal(id: string) {
    this.planToDelete = id;
    this.showDeleteModal = true;
    this.cdr.detectChanges(); 
  }

  closeDeleteModal() {
    this.showDeleteModal = false;
    this.planToDelete = null;
    this.cdr.detectChanges(); 
  }

  confirmDelete() {
    if (!this.planToDelete) return;
    this.isDeleting = true;
    this.cdr.detectChanges(); 

    this.planService.deletePlan(this.planToDelete).subscribe({
      next: () => {
        this.isDeleting = false;
        this.closeDeleteModal();
        this.loadPlans();
        this.toast.showSuccess(this.translate.instant('PLANS_PAGE.MSG_DELETE_SUCCESS') || 'Plan eliminado con éxito.');
      },
      error: (err) => {
        this.isDeleting = false;
        this.closeDeleteModal();
        this.toast.showError(err.error?.detail || 'Error al eliminar el plan.');
      }
    });
  }
}