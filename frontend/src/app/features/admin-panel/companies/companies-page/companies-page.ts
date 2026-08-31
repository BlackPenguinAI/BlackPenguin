import { Component, OnInit, ChangeDetectorRef } from '@angular/core';
import { CommonModule, DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { TranslateModule, TranslateService } from '@ngx-translate/core';

import { CompanyService } from '../services/company';
import { ToastService } from '../../../../core/services/toast';

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
  showEditModal: boolean = false;
  showDeleteModal: boolean = false;
  companyToDeleteId: string | null = null;
  selectedFile: File | null = null;

  form: any = {
    name: '',
    plan_id: '',
    start_date: new Date().toISOString().split('T')[0],
    duration_months: 12,
    admin_first_name: '',
    admin_last_name: '',
    admin_email: '',
    is_active: true,      // Company Status
    admin_is_active: true // User Status
  };

  editForm: any = {
    id: '',
    name: '',
    plan_id: '',
    start_date: '',
    duration_months: 12,
    admin_first_name: '',
    admin_last_name: '',
    admin_email: '',
    is_active: true,      
    admin_is_active: true 
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
            this.toast.showError(err.error?.detail || 'Error loading companies.');
            this.isLoading = false;
            this.cdr.detectChanges();
          }
        });
      },
      error: (err) => {
        this.toast.showError(err.error?.detail || 'Error loading subscription plans.');
        this.isLoading = false;
        this.cdr.detectChanges();
      }
    });
  }

  get calculatedEndDate(): string {
    if (!this.form.start_date || !this.form.duration_months) return '';
    const start = new Date(this.form.start_date);
    if (isNaN(start.getTime())) return '';
    start.setMonth(start.getMonth() + Number(this.form.duration_months));
    return start.toISOString().split('T')[0];
  }

  get editCalculatedEndDate(): string {
    if (!this.editForm.start_date || !this.editForm.duration_months) return '';
    const start = new Date(this.editForm.start_date);
    if (isNaN(start.getTime())) return '';
    start.setMonth(start.getMonth() + Number(this.editForm.duration_months));
    return start.toISOString().split('T')[0];
  }

  openModal(): void {
    this.form = {
      name: '',
      plan_id: this.plans.length > 0 ? this.plans[0].id : '',
      start_date: new Date().toISOString().split('T')[0],
      duration_months: 12,
      admin_first_name: '',
      admin_last_name: '',
      admin_email: '',
      is_active: true,
      admin_is_active: true
    };
    this.selectedFile = null;
    this.showModal = true;
    this.cdr.detectChanges();
  }

  closeModal(): void {
    this.showModal = false;
    this.cdr.detectChanges();
  }

  openEditModal(item: any): void {
    const admin = item.users && item.users.length > 0 
      ? item.users.find((u: any) => u.role === 'admin') || item.users[0]
      : null;

    this.editForm = {
      id: item.id,
      name: item.name,
      plan_id: item.plan_id || (item.plan?.id) || (this.plans.length > 0 ? this.plans[0].id : ''),
      start_date: item.license_start ? item.license_start.split('T')[0] : new Date().toISOString().split('T')[0],
      duration_months: 12,
      admin_first_name: admin ? admin.first_name : '',
      admin_last_name: admin ? admin.last_name : '',
      admin_email: admin ? admin.email : '',
      is_active: item.is_active !== undefined ? item.is_active : true,
      admin_is_active: admin ? (admin.is_active !== undefined ? admin.is_active : true) : true
    };
    this.selectedFile = null;
    this.showEditModal = true;
    this.cdr.detectChanges();
  }

  closeEditModal(): void {
    this.showEditModal = false;
    this.cdr.detectChanges();
  }

  onFileSelected(event: any): void {
    if (event.target.files && event.target.files.length > 0) {
      this.selectedFile = event.target.files[0];
      this.cdr.detectChanges();
    }
  }

  saveCompany(): void {
    if (!this.form.name || !this.form.admin_email || !this.form.plan_id) {
      this.toast.showError('Please complete all required fields.');
      return;
    }

    this.isSaving = true;
    this.cdr.detectChanges();

    const formData = new FormData();
    formData.append('name', this.form.name);
    formData.append('plan_id', this.form.plan_id);
    formData.append('duration_months', this.form.duration_months);
    formData.append('admin_first_name', this.form.admin_first_name);
    formData.append('admin_last_name', this.form.admin_last_name);
    formData.append('admin_email', this.form.admin_email);
    formData.append('is_active', this.form.is_active.toString());
    formData.append('admin_is_active', this.form.admin_is_active.toString());
    
    if (this.form.start_date) {
      formData.append('start_date', this.form.start_date);
    }

    if (this.selectedFile) {
      formData.append('receipt_file', this.selectedFile);
    }

    this.companyService.createCompany(formData).subscribe({
      next: (company: any) => {
        this.isSaving = false;
        this.closeModal();
        this.loadData();
        const administrator = company.users?.find((user: any) => user.role === 'admin');
        if (administrator?.auth_status === 'provisioning_failed') {
          this.toast.showError('Company registered, but Firebase could not deliver the activation link. Verify Firebase and use Resend activation.');
        } else if (administrator?.auth_status === 'suspended') {
          this.toast.showSuccess('Company registered. The Administrator is suspended, so no activation was sent.');
        } else {
          this.toast.showSuccess('Company registered. Firebase invitation sent to the Administrator.');
        }
      },
      error: (err) => {
        this.isSaving = false;
        this.cdr.detectChanges();
        this.toast.showError(err.error?.detail || 'Error registering the company.');
      }
    });
  }

  updateCompany(): void {
    if (!this.editForm.name || !this.editForm.plan_id) {
      this.toast.showError('Company name and plan are required.');
      return;
    }


    this.isSaving = true;
    this.cdr.detectChanges();

    const formData = new FormData();
    formData.append('name', this.editForm.name);
    formData.append('plan_id', this.editForm.plan_id);
    formData.append('duration_months', this.editForm.duration_months);
    formData.append('admin_first_name', this.editForm.admin_first_name);
    formData.append('admin_last_name', this.editForm.admin_last_name);
    formData.append('admin_email', this.editForm.admin_email);
    formData.append('is_active', this.editForm.is_active.toString());
    formData.append('admin_is_active', this.editForm.admin_is_active.toString());
    

    if (this.editForm.start_date) {
      formData.append('start_date', this.editForm.start_date);
    }

    if (this.selectedFile) {
      formData.append('receipt_file', this.selectedFile);
    }

    this.companyService.updateCompany(this.editForm.id, formData).subscribe({
      next: () => {
        this.isSaving = false;
        this.closeEditModal();
        this.loadData();
        this.toast.showSuccess('Company updated successfully.');
      },
      error: (err) => {
        this.isSaving = false;
        this.cdr.detectChanges();
        this.toast.showError(err.error?.detail || 'Error updating company.');
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
        this.toast.showSuccess('Activation link sent successfully.');
      },
      error: (err) => {
        this.resendingId = null;
        this.cdr.detectChanges();
        this.toast.showError(err.error?.detail || 'Error sending activation link.');
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
        this.toast.showSuccess('Company removed successfully.');
      },
      error: (err) => {
        this.isDeleting = false;
        this.closeDeleteModal();
        this.toast.showError(err.error?.detail || 'Error deleting company.');
      }
    });
  }
}
