import { Component, OnInit, ChangeDetectorRef } from '@angular/core';
import { CommonModule, DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { TranslateModule, TranslateService } from '@ngx-translate/core';

import { CompanyService } from './../services/company';
import { ToastService } from '../../../../core/services/toast';

// 🚀 IMPORTAMOS LOS COMPONENTES ATÓMICOS
import { GlassCardComponent } from '../../../../shared/ui/glass-card/glass-card';
import { InputComponent } from '../../../../shared/ui/input/input';
import { ButtonComponent } from '../../../../shared/ui/button/button';
import { ModalComponent } from '../../../../shared/ui/modal/modal';

@Component({
  selector: 'app-companies-page',
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
  providers: [DatePipe],
  templateUrl: './companies-page.html'
})
export class CompaniesPageComponent implements OnInit {
  companies: any[] = [];
  plans: any[] = [];
  
  isLoading: boolean = true;
  isSaving: boolean = false;
  isDeleting: boolean = false;
  resendingId: string | null = null;
  
  showModal: boolean = false;
  showDeleteModal: boolean = false;
  companyToDeleteId: string | null = null;
  selectedFile: File | null = null;

  form: any = {
    company_name: '',
    plan_id: '',
    duration_months: 12,
    admin_email: '',
    admin_password: '',
    admin_first_name: '',
    admin_paternal_last_name: '',
    admin_maternal_last_name: ''
  };

  constructor(
    private companyService: CompanyService,
    private toast: ToastService,
    private translate: TranslateService,
    private cdr: ChangeDetectorRef
  ) {}

  ngOnInit(): void {
    this.loadData();
  }

  loadData(): void {
    this.isLoading = true;
    this.companyService.getPlans().subscribe({
      next: (plansData) => {
        this.plans = plansData;
        this.companyService.getCompanies().subscribe({
          next: (companiesData) => {
            this.companies = companiesData;
            this.isLoading = false;
            this.cdr.detectChanges();
          },
          error: (err) => {
            this.toast.showError(err.error?.detail || 'Error al cargar empresas.');
            this.isLoading = false;
            this.cdr.detectChanges();
          }
        });
      },
      error: (err) => {
        this.toast.showError(err.error?.detail || 'Error al cargar planes.');
        this.isLoading = false;
        this.cdr.detectChanges();
      }
    });
  }

  openModal(): void {
    this.form = {
      company_name: '',
      plan_id: this.plans.length > 0 ? this.plans[0].id : '',
      duration_months: 12,
      admin_email: '',
      admin_password: '',
      admin_first_name: '',
      admin_paternal_last_name: '',
      admin_maternal_last_name: ''
    };
    this.selectedFile = null;
    this.showModal = true;
    this.cdr.detectChanges();
  }

  closeModal(): void {
    this.showModal = false;
    this.cdr.detectChanges();
  }

  onFileSelected(event: any): void {
    if (event.target.files && event.target.files.length > 0) {
      this.selectedFile = event.target.files[0];
      this.cdr.detectChanges();
    }
  }

  saveCompany(): void {
    if (!this.form.company_name || !this.form.admin_email || !this.form.admin_password || !this.form.plan_id) {
      this.toast.showError('Por favor completa todos los campos requeridos.');
      return;
    }

    this.isSaving = true;
    this.cdr.detectChanges();

    const formData = new FormData();
    Object.keys(this.form).forEach(key => {
      formData.append(key, this.form[key]);
    });

    if (this.selectedFile) {
      formData.append('payment_receipt', this.selectedFile);
    }

    this.companyService.createCompany(formData).subscribe({
      next: () => {
        this.isSaving = false;
        this.closeModal();
        this.loadData();
        this.toast.showSuccess(this.translate.instant('DEV_PAGE.MSG_CREATE_SUCCESS') || 'Empresa registrada con éxito.');
      },
      error: (err) => {
        this.isSaving = false;
        this.cdr.detectChanges();
        this.toast.showError(err.error?.detail || 'Error al registrar la empresa.');
      }
    });
  }

  resendActivationToken(id: string): void {
    this.resendingId = id;
    this.cdr.detectChanges();

    this.companyService.resendActivation(id).subscribe({
      next: () => {
        this.resendingId = null;
        this.cdr.detectChanges();
        this.toast.showSuccess(this.translate.instant('DEV_PAGE.MSG_RESEND_SUCCESS') || 'Enlace de activación enviado.');
      },
      error: (err) => {
        this.resendingId = null;
        this.cdr.detectChanges();
        this.toast.showError(err.error?.detail || 'Error al reenviar la activación.');
      }
    });
  }

  openDeleteModal(id: string): void {
    this.companyToDeleteId = id;
    this.showDeleteModal = true;
    this.cdr.detectChanges();
  }

  closeDeleteModal(): void {
    this.showDeleteModal = false;
    this.companyToDeleteId = null;
    this.cdr.detectChanges();
  }

  confirmDelete(): void {
    if (!this.companyToDeleteId) return;
    this.isDeleting = true;
    this.cdr.detectChanges();

    this.companyService.deleteCompany(this.companyToDeleteId).subscribe({
      next: () => {
        this.isDeleting = false;
        this.closeDeleteModal();
        this.loadData();
        this.toast.showSuccess(this.translate.instant('DEV_PAGE.MSG_DELETE_SUCCESS') || 'Empresa eliminada exitosamente.');
      },
      error: (err) => {
        this.isDeleting = false;
        this.closeDeleteModal();
        this.toast.showError(err.error?.detail || 'Error al eliminar la empresa.');
      }
    });
  }
}