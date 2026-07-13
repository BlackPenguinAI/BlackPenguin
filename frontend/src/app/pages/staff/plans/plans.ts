import { Component, OnInit, isDevMode, ChangeDetectorRef } from '@angular/core'; // 🚀 Importado ChangeDetectorRef
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { TranslateModule, TranslateService } from '@ngx-translate/core';
import { ToastService } from '../../../core/services/toast';

@Component({
  selector: 'app-staff-plans',
  standalone: true,
  imports: [CommonModule, FormsModule, TranslateModule],
  templateUrl: './plans.html',
  styleUrl: './plans.scss'
})
export class StaffPlansComponent implements OnInit {
  plans: any[] = [];
  isLoading: boolean = true;
  isSaving: boolean = false;
  
  showModal: boolean = false;
  isEditing: boolean = false;
  currentPlanId: string | null = null;
  
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
    private http: HttpClient,
    private translate: TranslateService,
    private toast: ToastService,
    private cdr: ChangeDetectorRef // 🚀 Inyectamos el control de renderizado
  ) {}

  private get apiUrl() {
    return isDevMode() 
      ? 'http://localhost:8000/api/v1/tenants/plans/' 
      : 'https://blackpenguin.ai/api/v1/tenants/plans/';
  }

  private get headers() {
    const token = localStorage.getItem('bp_token');
    return new HttpHeaders().set('Authorization', `Bearer ${token}`);
  }

  ngOnInit() {
    this.loadPlans();
  }

  loadPlans() {
    this.isLoading = true;
    this.cdr.detectChanges(); // 🚀 Mostramos el spinner

    this.http.get<any[]>(this.apiUrl, { headers: this.headers }).subscribe({
      next: (data) => {
        this.plans = data;
        this.isLoading = false;
        this.cdr.detectChanges(); // 🚀 Mostramos los planes al instante
      },
      error: (err) => {
        console.error('Error loading plans:', err);
        this.isLoading = false;
        this.cdr.detectChanges(); // 🚀 Ocultamos el spinner si falla
      }
    });
  }

  openModal(plan?: any) {
    if (plan) {
      this.isEditing = true;
      this.currentPlanId = plan.id;
      this.form = { ...plan };
    } else {
      this.isEditing = false;
      this.currentPlanId = null;
      this.form = {
        name: '',
        description: '',
        max_admins: 1,
        max_mkt_users: 0,
        max_sales_users: 0,
        max_projects: 1,
        max_properties_per_project: 50,
        is_active: true
      };
    }
    this.showModal = true;
    this.cdr.detectChanges(); // 🚀 Abrimos el modal instantáneamente
  }

  closeModal() {
    this.showModal = false;
    this.currentPlanId = null;
    this.cdr.detectChanges(); // 🚀 Cerramos el modal instantáneamente
  }

  savePlan() {
    this.isSaving = true;
    this.cdr.detectChanges(); // 🚀 Mostramos el estado "Guardando..." en el botón

    if (this.isEditing && this.currentPlanId) {
      this.http.put(`${this.apiUrl}${this.currentPlanId}`, this.form, { headers: this.headers }).subscribe({
        next: () => {
          this.isSaving = false;
          this.closeModal();
          this.loadPlans();
          this.toast.showSuccess(this.translate.instant('PLANS_PAGE.MSG_SAVE_SUCCESS') || 'Plan actualizado con éxito.');
        },
        error: (err) => {
          this.isSaving = false;
          this.cdr.detectChanges(); // 🚀 Restauramos el botón si hubo error
          this.toast.showError(err.error?.detail || 'Error al actualizar el plan.'); // 🚀 Reemplazamos alert() por Toast
        }
      });
    } else {
      this.http.post(this.apiUrl, this.form, { headers: this.headers }).subscribe({
        next: () => {
          this.isSaving = false;
          this.closeModal();
          this.loadPlans();
          this.toast.showSuccess(this.translate.instant('PLANS_PAGE.MSG_CREATE_SUCCESS') || 'Plan creado con éxito.');
        },
        error: (err) => {
          this.isSaving = false;
          this.cdr.detectChanges(); // 🚀 Restauramos el botón si hubo error
          this.toast.showError(err.error?.detail || 'Error al crear el plan.'); // 🚀 Reemplazamos alert() por Toast
        }
      });
    }
  }

  openDeleteModal(id: string) {
    this.planToDelete = id;
    this.showDeleteModal = true;
    this.cdr.detectChanges(); // 🚀 Mostramos modal de alerta al instante
  }

  closeDeleteModal() {
    this.showDeleteModal = false;
    this.planToDelete = null;
    this.cdr.detectChanges(); // 🚀 Ocultamos modal de alerta al instante
  }

  confirmDelete() {
    if (!this.planToDelete) return;
    this.isDeleting = true;
    this.cdr.detectChanges(); // 🚀 Mostramos el spinner en el botón de borrar

    this.http.delete(`${this.apiUrl}${this.planToDelete}`, { headers: this.headers }).subscribe({
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