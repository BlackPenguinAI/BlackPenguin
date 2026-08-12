import { CommonModule } from '@angular/common';
import { ChangeDetectorRef, Component, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { forkJoin } from 'rxjs';

import {
  CompanyUser,
  CompanyUserInvite,
  CompanyUserLimits,
  CompanyUserRole,
  CompanyUsersService,
} from '../../../core/services/company-users.service';
import { ToastService } from '../../../core/services/toast';

@Component({
  selector: 'app-company-users',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './company-users.html',
})
export class CompanyUsersComponent implements OnInit {
  users: CompanyUser[] = [];
  limits: CompanyUserLimits | null = null;
  loading = true;
  saving = false;
  invite: CompanyUserInvite = { first_name: '', last_name: '', email: '', role: 'assistant' };

  constructor(
    private companyUsers: CompanyUsersService,
    private toast: ToastService,
    private cdr: ChangeDetectorRef,
  ) {}

  ngOnInit(): void { this.load(); }

  load(): void {
    this.loading = true;
    forkJoin({ users: this.companyUsers.list(), limits: this.companyUsers.limits() }).subscribe({
      next: ({ users, limits }) => {
        this.users = users;
        this.limits = limits;
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
    this.companyUsers.invite(this.invite).subscribe({
      next: user => {
        this.users = [...this.users, user].sort((a, b) => a.email.localeCompare(b.email));
        this.invite = { first_name: '', last_name: '', email: '', role: 'assistant' };
        this.saving = false;
        this.toast.showSuccess('Invitation created');
        this.reloadLimits();
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
    this.companyUsers.setActive(user.id, is_active).subscribe({
      next: updated => {
        Object.assign(user, updated);
        this.reloadLimits();
        this.cdr.markForCheck();
      },
      error: err => this.toast.showError(err.error?.detail || 'Could not update user'),
    });
  }

  resendActivation(user: CompanyUser): void {
    this.companyUsers.resendActivation(user.id).subscribe({
      next: () => this.toast.showSuccess('Activation link sent'),
      error: err => this.toast.showError(err.error?.detail || 'Could not resend activation'),
    });
  }

  get administrator(): CompanyUser | undefined {
    return this.users.find(user => user.role === 'admin');
  }

  get teamUsers(): CompanyUser[] {
    return this.users.filter(user => user.role !== 'admin');
  }

  roleLabel(role: CompanyUserRole): string {
    return ({ admin: 'Administrator', assistant: 'Assistant', mkt: 'Marketing', sales: 'Sales' })[role];
  }

  private reloadLimits(): void {
    this.companyUsers.limits().subscribe({
      next: limits => { this.limits = limits; this.cdr.markForCheck(); },
    });
  }
}
