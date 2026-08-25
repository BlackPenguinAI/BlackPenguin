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
import { ButtonComponent } from '../../../shared/ui/button/button';
import { InputComponent } from '../../../shared/ui/input/input';
import { ModalComponent } from '../../../shared/ui/modal/modal';

@Component({
  selector: 'app-company-users',
  standalone: true,
  imports: [CommonModule, FormsModule, ButtonComponent, InputComponent, ModalComponent],
  templateUrl: './company-users.html',
})
export class CompanyUsersComponent implements OnInit {
  users: CompanyUser[] = [];
  limits: CompanyUserLimits | null = null;
  loading = true;
  saving = false;
  showAddModal = false;
  repeatPassword = '';
  invite: CompanyUserInvite = this.emptyForm();

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

  openAddModal(): void {
    this.invite = this.emptyForm();
    this.repeatPassword = '';
    this.showAddModal = true;
  }

  closeAddModal(): void {
    if (!this.saving) this.showAddModal = false;
  }

  sendInvite(): void {
    if (!this.formValid) return;
    this.saving = true;
    this.companyUsers.invite(this.invite).subscribe({
      next: user => {
        this.users = [...this.users, user].sort((a, b) => a.email.localeCompare(b.email));
        this.invite = this.emptyForm();
        this.repeatPassword = '';
        this.showAddModal = false;
        this.saving = false;
        this.toast.showSuccess('User created');
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

  get formValid(): boolean {
    return !!(
      this.invite.first_name.trim() && this.invite.last_name.trim() &&
      /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(this.invite.email.trim()) &&
      this.invite.password.length >= 4 && this.invite.password === this.repeatPassword
    );
  }

  private emptyForm(): CompanyUserInvite {
    return { first_name: '', last_name: '', email: '', role: 'assistant', password: '', is_active: true };
  }

  private reloadLimits(): void {
    this.companyUsers.limits().subscribe({
      next: limits => { this.limits = limits; this.cdr.markForCheck(); },
    });
  }
}
