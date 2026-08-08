import { Component, OnInit, isDevMode, ChangeDetectorRef } from '@angular/core'; // 🚀 Importado ChangeDetectorRef
import { CommonModule, DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { TranslateModule, TranslateService } from '@ngx-translate/core';
import { ToastService } from '../../../core/services/toast';
import { SelectComponent, SelectOption } from '../../../shared/ui/select/select';

@Component({
  selector: 'app-staff-developers',
  standalone: true,
  imports: [CommonModule, FormsModule, TranslateModule, SelectComponent],
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
    admin_password: '', // 🚀 NUEVO CAMPO EN EL FORMULARIO
    admin_first_name: '',        
    admin_paternal_last_name: '',  
    admin_maternal_last_name: '',  
    payment_receipt_url: '',
    is_active: true
  };

  get planOptions(): SelectOption[] {
    return [
      { label: this.translate.instant('DEV_PAGE.SEL_PLAN'), value: '', disabled: true },
      ...this.plans.map((plan) => ({
        label: plan.name,
        value: plan.id
      }))
    ];
  }

  constructor(
    private http: HttpClient, 
    private translate: TranslateService,
    private datePipe: DatePipe,
    private toast: ToastService,
    private cdr: ChangeDetectorRef // 🚀 Inyectamos el control de renderizado
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
    this.cdr.detectChanges(); // 🚀 Forzamos a mostrar el loader

    this.http.get<any[]>(this.plansUrl, { headers: this.headers }).subscribe({
      next: (plansData) => {
        this.plans = plansData;
        
        // Llamada anidada para asegurar que tenemos los planes antes que los developers
        this.http.get<any[]>(this.apiUrl, { headers: this.headers }).subscribe({
          next: (devData) => {
            this.developers = devData;
            this.isLoading = false;
            this.cdr.detectChanges(); // 🚀 Mostramos la tabla al instante
          },
          error: () => {
            this.isLoading = false;
            this.cdr.detectChanges(); // 🚀 Ocultamos el loader si falla
          }
        });
      },
      error: () => {
        this.isLoading = false;
        this.cdr.detectChanges(); // 🚀 Ocultamos el loader si falla la carga de planes
      }
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
      this.form.admin_password = '';  // para que no se quede pegada la contraseña del cliente anterior

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
    this.cdr.detectChanges(); // 🚀 Forzamos que el modal aparezca de inmediato
  }

  closeModal() {
    this.showModal = false;
    this.cdr.detectChanges(); // 🚀 Forzamos que el modal desaparezca de inmediato
  }

  saveDeveloper() {
    if (!this.form.company_name || !this.form.plan_id) return;
    this.isSaving = true;
    this.cdr.detectChanges();

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
          this.cdr.detectChanges(); // 🚀 Actualizamos el botón si hubo error
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
          this.cdr.detectChanges(); // 🚀 Actualizamos el botón si hubo error
          this.toast.showError(err.error?.detail || 'Error during developer onboarding');
        }
      });
    }
  }

  resendActivation(companyId: string) {
    this.resendingId = companyId;
    this.cdr.detectChanges(); // 🚀 Mostramos el spinner en el botón de reenviar

    const url = `${this.apiUrl}/${companyId}/resend-activation?lang=${this.translate.currentLang}`;
    
    this.http.post(url, {}, { headers: this.headers }).subscribe({
      next: () => {
        this.resendingId = null;
        this.cdr.detectChanges(); // 🚀 Restauramos el botón
        this.toast.showSuccess(this.translate.instant('DEV_PAGE.MSG_RESEND_SUCCESS') || 'Activation link sent.');
      },
      error: (err) => {
        this.resendingId = null;
        this.cdr.detectChanges(); // 🚀 Restauramos el botón
        this.toast.showError(err.error?.detail || 'Failed to resend token.');
      }
    });
  }

  openDeleteModal(id: string) {
    this.developerToDelete = id;
    this.showDeleteModal = true;
    this.cdr.detectChanges(); // 🚀 Mostramos el modal de advertencia
  }

  closeDeleteModal() {
    this.showDeleteModal = false;
    this.developerToDelete = null;
    this.cdr.detectChanges(); // 🚀 Ocultamos el modal de advertencia
  }

  confirmDelete() {
    if (!this.developerToDelete) return;
    this.isDeleting = true;
    this.cdr.detectChanges(); // 🚀 Mostramos spinner en el botón eliminar

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
