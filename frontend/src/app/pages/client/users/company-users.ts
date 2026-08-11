import { CommonModule } from '@angular/common';
import { ChangeDetectorRef, Component, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { HttpClient } from '@angular/common/http';

import { API_V1_URL } from '../../../core/config/api.config';
import { ToastService } from '../../../core/services/toast';

interface CompanyUser {
  id: string; email: string; first_name?: string; last_name?: string;
  role: 'admin' | 'mkt' | 'sales'; is_active: boolean;
}

@Component({
  selector: 'app-company-users',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './company-users.html',
})
export class CompanyUsersComponent implements OnInit {
  users: CompanyUser[] = [];
  loading = true;
  saving = false;
  invite = { first_name: '', last_name: '', email: '', role: 'sales' as CompanyUser['role'] };

  constructor(
    private http: HttpClient,
    private toast: ToastService,
    private cdr: ChangeDetectorRef,
  ) {}

  ngOnInit(): void { this.load(); }

  load(): void {
    this.loading = true;
    this.http.get<CompanyUser[]>(`${API_V1_URL}/users/company`).subscribe({
      next: users => {
        this.users = users;
        this.loading = false;
        this.cdr.markForCheck();
      },
      error: err => {
        this.loading = false;
        this.toast.showError(err.error?.detail || 'Could not load users');
        this.cdr.markForCheck();
      },
    });
  }

  sendInvite(): void {
    if (!this.invite.email || !this.invite.first_name || !this.invite.last_name) return;
    this.saving = true;
    this.http.post<CompanyUser>(`${API_V1_URL}/users/company`, this.invite).subscribe({
      next: user => {
        this.users = [...this.users, user].sort((a, b) => a.email.localeCompare(b.email));
        this.invite = { first_name: '', last_name: '', email: '', role: 'sales' };
        this.saving = false;
        this.toast.showSuccess('Invitation created');
        this.cdr.markForCheck();
      },
      error: err => {
        this.saving = false;
        this.toast.showError(err.error?.detail || 'Could not invite user');
        this.cdr.markForCheck();
      },
    });
  }

  setActive(user: CompanyUser, is_active: boolean): void {
    this.http.patch<CompanyUser>(`${API_V1_URL}/users/company/${user.id}`, { is_active }).subscribe({
      next: updated => {
        Object.assign(user, updated);
        this.cdr.markForCheck();
      },
      error: err => this.toast.showError(err.error?.detail || 'Could not update user'),
    });
  }
}
