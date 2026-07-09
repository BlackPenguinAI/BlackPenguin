import { Component, OnInit, isDevMode } from '@angular/core';
import { CommonModule, DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { TranslateModule, TranslateService } from '@ngx-translate/core';
import { ToastService } from '../../../core/services/toast'; // 🚀 Importar el servicio Toast de tu app

@Component({
  selector: 'app-staff-developers',
  standalone: true,
  imports: [CommonModule, FormsModule, TranslateModule],
  providers: [DatePipe],
  templateUrl: './developers.html',
  styleUrl: './developers.scss'
})
export class StaffDevelopersComponent implements OnInit {
  developers: any[] = [];
  plans: any[] = [];
  
  isLoading: boolean = true;
  isSaving: boolean = false;
  resendingId: string | null = null;
  
  showModal: boolean = false;
  isEditing: boolean = false;
  currentDevId: string | null = null;

  showDeleteModal: boolean = false;
  developerToDelete: string | null = null;
  isDeleting: boolean = false;
  
  form: any = {
    company_name: '',
    plan_id: '',
    duration_months: 12,
    admin_email: '',
    admin_first_name: '',        // 🚀 Campos atómicos requeridos
    admin_paternal_last_name: '',  // 🚀 Campos atómicos requeridos
    admin_maternal_last_name: '',  // 🚀 Campos atómicos requeridos
    payment_receipt_url: '',
    is_active: true
  };

  constructor(
    private http: HttpClient, 
    private translate: TranslateService,
    private datePipe: DatePipe,
    private toast: ToastService // 🚀 Inyectar servicio de Toasts
  ) {}

  private get apiUrl() {
    return isDevMode() ? 'http://localhost:8000/api/v1/tenants/developers' : 'https://blackpenguin.ai/api/v1/tenants/developers';
  }

  private get plansUrl() {
    return isDevMode() ? 'http://localhost:8000/api/v1/tenants/plans' : 'https://blackpenguin.ai/api/v1/tenants/plans';
  }

  private get headers() {
    const token = localStorage.getItem('bp_token');
    return new HttpHeaders().set('Authorization', `Bearer ${token}`);
  }

  ngOnInit() {
    this.loadPlansAndDevelopers();
  }

  loadPlansAndDevelopers() {
    this.isLoading = true;
    this.http.get<any[]>(this.plansUrl, { headers: this.headers }).subscribe({
      next: (plansData) => {
        this.plans = plansData;
        this.http.get<any[]>(this.apiUrl, { headers: this.headers }).subscribe({
          next: (devData) => {
            this.developers = devData;
            this.isLoading = false;
          },
          error: () => this.isLoading = false
        });
      },
      error: () => this.isLoading = false
    });
  }

  getPlanName(planId: string): string {
    const plan = this.plans.find(p => p.id === planId);
    return plan ? plan.name : 'Sin Plan';
  }

  openModal(dev?: any) {
    if (dev) {
      this.isEditing = true;
      this.currentDevId = dev.id;
      
      // 🚀 CARGA AUTOMÁTICA: Mapeamos los datos exactos que vienen de la base de datos
      this.form = {
        company_name: dev.name,
        plan_id: dev.plan_id || '',
        duration_months: dev.plan_duration_months,
        admin_email: dev.admin_email || '', 
        admin_first_name: dev.admin_first_name || '',
        admin_paternal_last_name: dev.admin_paternal_last_name || '',
        admin_maternal_last_name: dev.admin_maternal_last_name || '',
        payment_receipt_url: dev.payment_receipt_url || '',
        is_active: dev.is_active
      };
    } else {
      this.isEditing = false;
      this.currentDevId = null;
      this.form = {
        company_name: '',
        plan_id: this.plans.length > 0 ? this.plans[0].id : '',
        duration_months: 12,
        admin_email: '',
        admin_first_name: '',
        admin_paternal_last_name: '',
        admin_maternal_last_name: '',
        payment_receipt_url: '',
        is_active: true
      };
    }
    this.showModal = true;
  }

  closeModal() {
    this.showModal = false;
  }

  saveDeveloper() {
    if (!this.form.company_name || !this.form.plan_id) return;
    this.isSaving = true;

    // Aseguramos limpieza estricta de strings antes de enviar la carga útil
    const payload = {
      ...this.form,
      company_name: this.form.company_name.trim(),
      admin_first_name: this.form.admin_first_name.trim(),
      admin_paternal_last_name: this.form.admin_paternal_last_name.trim(),
      admin_maternal_last_name: this.form.admin_maternal_last_name ? this.form.admin_maternal_last_name.trim() : '',
      admin_email: this.form.admin_email.trim(),
      language: this.translate.currentLang
    };

    if (!payload.payment_receipt_url) delete payload.payment_receipt_url;

    if (this.isEditing && this.currentDevId) {
      this.http.put(`${this.apiUrl}/${this.currentDevId}`, payload, { headers: this.headers }).subscribe({
        next: () => {
          this.isSaving = false;
          this.closeModal();
          this.loadPlansAndDevelopers();
          this.toast.showSuccess(this.translate.instant('DEV_PAGE.MSG_UPDATED_SUCCESS') || 'Developer profile updated!');
        },
        error: (err) => {
          this.isSaving = false;
          this.toast.showError(err.error?.detail || 'Error updating developer profile');
        }
      });
    } else {
      this.http.post(this.apiUrl, payload, { headers: this.headers }).subscribe({
        next: () => {
          this.isSaving = false;
          this.closeModal();
          this.loadPlansAndDevelopers();
          this.toast.showSuccess(this.translate.instant('DEV_PAGE.MSG_CREATED_SUCCESS') || 'Developer onboarded successfully!');
        },
        error: (err) => {
          this.isSaving = false;
          this.toast.showError(err.error?.detail || 'Error during developer onboarding');
        }
      });
    }
  }

  resendActivation(companyId: string) {
    this.resendingId = companyId;
    const url = `${this.apiUrl}/${companyId}/resend-activation?lang=${this.translate.currentLang}`;
    
    this.http.post(url, {}, { headers: this.headers }).subscribe({
      next: () => {
        this.resendingId = null;
        this.toast.showSuccess(this.translate.instant('DEV_PAGE.MSG_RESEND_SUCCESS') || 'Activation link sent.');
      },
      error: (err) => {
        this.resendingId = null;
        this.toast.showError(err.error?.detail || 'Failed to resend token.');
      }
    });
  }

  // 🚀 NUEVAS FUNCIONES PARA EL MODAL DE ELIMINAR
  openDeleteModal(id: string) {
    this.developerToDelete = id;
    this.showDeleteModal = true;
  }

  closeDeleteModal() {
    this.showDeleteModal = false;
    this.developerToDelete = null;
  }

  confirmDelete() {
    if (!this.developerToDelete) return;
    this.isDeleting = true;

    this.http.delete(`${this.apiUrl}/${this.developerToDelete}`, { headers: this.headers }).subscribe({
      next: () => {
        this.isDeleting = false;
        this.closeDeleteModal();
        this.loadPlansAndDevelopers();
        this.toast.showSuccess(this.translate.instant('DEV_PAGE.MSG_DELETE_SUCCESS') || 'Developer removed successfully.');
      },
      error: (err) => {
        this.isDeleting = false;
        this.closeDeleteModal();
        this.toast.showError(err.error?.detail || 'Error removing developer');
      }
    });
  }
}