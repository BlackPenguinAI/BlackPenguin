import { Component, OnInit, ChangeDetectorRef, isDevMode } from '@angular/core';
import { CommonModule, DecimalPipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { ToastService } from '../../../../core/services/toast';

import { GlassCardComponent } from '../../../../shared/ui/glass-card/glass-card';
import { InputComponent } from '../../../../shared/ui/input/input';
import { ButtonComponent } from '../../../../shared/ui/button/button';

@Component({
  selector: 'app-users-page',
  standalone: true,
  imports: [
    CommonModule, 
    FormsModule, 
    GlassCardComponent, 
    InputComponent, 
    ButtonComponent
  ],
  providers: [DecimalPipe],
  templateUrl: './users-page.html'
})
export class UsersPageComponent implements OnInit {
  users: any[] = [];
  companies: any[] = [];
  
  isLoading: boolean = true;

  // Filtros
  filters = {
    company_id: '',
    role: '',
    first_name: '',
    last_name: '',
    email: ''
  };

  roles = [
    { label: 'All Roles', value: '' },
    { label: 'Superadmin', value: 'superadmin' },
    { label: 'Admin', value: 'admin' },
    { label: 'Marketing', value: 'mkt' },
    { label: 'Sales', value: 'sales' }
  ];

  constructor(
    private http: HttpClient,
    private toast: ToastService,
    private cdr: ChangeDetectorRef
  ) {}

  ngOnInit(): void {
    this.loadCompanies();
    this.loadUsers();
  }

  private get baseUrl() {
    return isDevMode() ? 'http://localhost:8000' : 'https://blackpenguin.ai';
  }

  private get headers() {
    const token = localStorage.getItem('bp_token');
    return new HttpHeaders().set('Authorization', `Bearer ${token}`);
  }

  loadCompanies(): void {
    this.http.get<any[]>(`${this.baseUrl}/api/v1/companies/`, { headers: this.headers }).subscribe({
      next: (data) => {
        this.companies = data;
        this.cdr.detectChanges();
      }
    });
  }

  loadUsers(): void {
    this.isLoading = true;
    this.cdr.detectChanges();

    // Construcción de Query Params
    let params: string[] = [];
    if (this.filters.company_id) params.push(`company_id=${this.filters.company_id}`);
    if (this.filters.role) params.push(`role=${this.filters.role}`);
    if (this.filters.first_name) params.push(`first_name=${encodeURIComponent(this.filters.first_name)}`);
    if (this.filters.last_name) params.push(`last_name=${encodeURIComponent(this.filters.last_name)}`);
    if (this.filters.email) params.push(`email=${encodeURIComponent(this.filters.email)}`);

    const queryString = params.length > 0 ? `?${params.join('&')}` : '';

    this.http.get<any[]>(`${this.baseUrl}/api/v1/users/all${queryString}`, { headers: this.headers }).subscribe({
      next: (data) => {
        this.users = data;
        this.isLoading = false;
        this.cdr.detectChanges();
      },
      error: () => {
        this.toast.showError('Failed to load users list.');
        this.isLoading = false;
        this.cdr.detectChanges();
      }
    });
  }

  resetFilters(): void {
    this.filters = {
      company_id: '',
      role: '',
      first_name: '',
      last_name: '',
      email: ''
    };
    this.loadUsers();
  }
}