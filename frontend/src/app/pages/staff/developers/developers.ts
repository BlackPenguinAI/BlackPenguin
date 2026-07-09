import { Component, OnInit, isDevMode } from '@angular/core';
import { CommonModule, DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { TranslateModule, TranslateService } from '@ngx-translate/core';

@Component({
  selector: 'app-staff-developers',
  standalone: true,
  imports: [CommonModule, FormsModule, TranslateModule],
  providers: [DatePipe],
  templateUrl: './developers.html',
  styleUrl: './developers.scss'
})
export class StaffDevelopersComponent implements OnInit {
  companies: any[] = [];
  isLoading: boolean = true;
  isSaving: boolean = false;
  
  // Control del Modal
  showModal: boolean = false;
  isEditing: boolean = false;
  currentCompanyId: string | null = null;
  
  // Formulario
  form = {
    name: '',
    plan_tier: 'core',
    max_projects_allowed: 3,
    license_end: '',
    has_voice_agents: false,
    has_enterprise_integrations: false,
    is_active: true
  };

  constructor(
    private http: HttpClient, 
    private translate: TranslateService,
    private datePipe: DatePipe
  ) {}

  private get apiUrl() {
    return isDevMode() 
      ? 'http://localhost:8000/api/v1/tenants/' 
      : 'https://blackpenguin.ai/api/v1/tenants/';
  }

  private get headers() {
    const token = localStorage.getItem('bp_token');
    return new HttpHeaders().set('Authorization', `Bearer ${token}`);
  }

  ngOnInit() {
    this.loadCompanies();
  }

  loadCompanies() {
    this.isLoading = true;
    this.http.get<any[]>(this.apiUrl, { headers: this.headers }).subscribe({
      next: (data) => {
        this.companies = data;
        this.isLoading = false;
      },
      error: (err) => {
        console.error('Error loading developers:', err);
        this.isLoading = false;
      }
    });
  }

  openModal(company?: any) {
    if (company) {
      this.isEditing = true;
      this.currentCompanyId = company.id;
      this.form = {
        name: company.name,
        plan_tier: company.plan_tier,
        max_projects_allowed: company.max_projects_allowed,
        // Formatear fecha para el input type="date"
        license_end: this.datePipe.transform(company.license_end, 'yyyy-MM-dd') || '',
        has_voice_agents: company.has_voice_agents,
        has_enterprise_integrations: company.has_enterprise_integrations,
        is_active: company.is_active
      };
    } else {
      this.isEditing = false;
      this.currentCompanyId = null;
      // Default: licencia de 1 año
      const nextYear = new Date();
      nextYear.setFullYear(nextYear.getFullYear() + 1);
      
      this.form = {
        name: '',
        plan_tier: 'core',
        max_projects_allowed: 3,
        license_end: this.datePipe.transform(nextYear, 'yyyy-MM-dd') || '',
        has_voice_agents: false,
        has_enterprise_integrations: false,
        is_active: true
      };
    }
    this.showModal = true;
  }

  closeModal() {
    this.showModal = false;
  }

  saveCompany() {
    if (!this.form.name || !this.form.license_end) return;

    this.isSaving = true;
    
    // Transformar fecha al formato ISO que espera FastAPI
    const payload = {
      ...this.form,
      license_end: new Date(this.form.license_end).toISOString()
    };

    if (this.isEditing && this.currentCompanyId) {
      this.http.put(`${this.apiUrl}${this.currentCompanyId}`, payload, { headers: this.headers }).subscribe({
        next: () => {
          this.isSaving = false;
          this.closeModal();
          this.loadCompanies();
        },
        error: (err) => {
          this.isSaving = false;
          alert('Error al actualizar: ' + (err.error?.detail || err.message));
        }
      });
    } else {
      this.http.post(this.apiUrl, payload, { headers: this.headers }).subscribe({
        next: () => {
          this.isSaving = false;
          this.closeModal();
          this.loadCompanies();
        },
        error: (err) => {
          this.isSaving = false;
          alert('Error al crear: ' + (err.error?.detail || err.message));
        }
      });
    }
  }

  deleteCompany(id: string) {
    const confirmMsg = this.translate.instant('ADMIN.CONFIRM_DELETE') || 'Are you sure?';
    if (confirm(confirmMsg)) {
      this.http.delete(`${this.apiUrl}${id}`, { headers: this.headers }).subscribe({
        next: () => this.loadCompanies(),
        error: (err) => alert('Error al eliminar')
      });
    }
  }
}