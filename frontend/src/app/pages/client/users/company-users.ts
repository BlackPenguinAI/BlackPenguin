import { CommonModule } from '@angular/common';
import { ChangeDetectorRef, Component, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { forkJoin } from 'rxjs';

import {
  CompanyProjectOption, CompanyUser, CompanyUserInvite, CompanyUserLimits,
  CompanyUserRole, CompanyUsersService,
} from '../../../core/services/company-users.service';
import { deviceTimezone, filterTimezoneOptions, timezoneLabel } from '../../../core/timezones';
import { ToastService } from '../../../core/services/toast';
import { ButtonComponent } from '../../../shared/ui/button/button';
import { InputComponent } from '../../../shared/ui/input/input';
import { ModalComponent } from '../../../shared/ui/modal/modal';

@Component({
  selector: 'app-company-users', standalone: true,
  imports: [CommonModule, FormsModule, ButtonComponent, InputComponent, ModalComponent],
  templateUrl: './company-users.html',
})
export class CompanyUsersComponent implements OnInit {
  users: CompanyUser[] = [];
  projects: CompanyProjectOption[] = [];
  limits: CompanyUserLimits | null = null;
  loading = true; saving = false; showAddModal = false;
  editingUserId: string | null = null;
  timezoneSearch = '';
  invite: CompanyUserInvite = this.emptyForm();
  readonly timezoneLabel = timezoneLabel;

  constructor(private companyUsers: CompanyUsersService, private toast: ToastService, private cdr: ChangeDetectorRef) {}
  ngOnInit(): void { this.load(); }

  load(): void {
    this.loading = true;
    forkJoin({ users: this.companyUsers.list(), limits: this.companyUsers.limits(), projects: this.companyUsers.projects() }).subscribe({
      next: ({ users, limits, projects }) => {
        this.users = users; this.limits = limits; this.projects = projects; this.loading = false; this.cdr.markForCheck();
      },
      error: err => { this.loading = false; this.toast.showError(err.error?.detail || 'Could not load users'); this.cdr.markForCheck(); },
    });
  }

  openAddModal(): void {
    this.editingUserId = null; this.invite = this.emptyForm();
    this.timezoneSearch = ''; this.showAddModal = true;
  }

  openEditModal(user: CompanyUser): void {
    this.editingUserId = user.id;
    this.invite = {
      first_name: user.first_name || '', last_name: user.last_name || '', email: user.email,
      role: user.role === 'admin' ? 'assistant' : user.role, is_active: user.is_active,
      timezone: user.timezone || deviceTimezone(), project_access_scope: user.project_access_scope || 'all',
      project_ids: [...(user.project_ids || [])],
    };
    this.timezoneSearch = ''; this.showAddModal = true;
  }

  closeAddModal(): void { if (!this.saving) this.showAddModal = false; }

  saveUser(): void {
    if (!this.formValid) return;
    this.saving = true;
    const request = this.editingUserId
      ? this.companyUsers.update(this.editingUserId, {
          first_name: this.invite.first_name, last_name: this.invite.last_name, role: this.invite.role,
          is_active: this.invite.is_active, timezone: this.invite.timezone || deviceTimezone(),
          project_access_scope: this.invite.project_access_scope || 'all', project_ids: this.invite.project_ids || [],
        })
      : this.companyUsers.invite(this.invite);
    request.subscribe({
      next: user => {
        const index = this.users.findIndex(item => item.id === user.id);
        this.users = index < 0 ? [...this.users, user] : this.users.map(item => item.id === user.id ? user : item);
        this.users.sort((a, b) => a.email.localeCompare(b.email));
        this.showAddModal = false; this.saving = false;
        this.toast.showSuccess(this.editingUserId ? 'User updated' :
          (user.auth_status === 'provisioning_failed' ? 'User saved, but Firebase rejected the activation request.' : 'Activation request accepted by Firebase'));
        this.reloadLimits(); this.cdr.markForCheck();
      },
      error: err => { this.saving = false; this.toast.showError(err.error?.detail || 'Could not save user'); this.cdr.markForCheck(); },
    });
  }

  setActive(user: CompanyUser, is_active: boolean): void {
    this.companyUsers.setActive(user.id, is_active).subscribe({
      next: updated => { Object.assign(user, updated); this.reloadLimits(); this.cdr.markForCheck(); },
      error: err => this.toast.showError(err.error?.detail || 'Could not update user'),
    });
  }

  resendActivation(user: CompanyUser): void {
    this.companyUsers.resendActivation(user.id).subscribe({
      next: result => {
        user.auth_status = 'invited';
        user.invitation_sent_at = result.sent_at;
        this.toast.showSuccess('Activation request accepted by Firebase');
        this.cdr.markForCheck();
      },
      error: err => this.toast.showError(err.error?.detail || 'Could not resend activation'),
    });
  }

  authStatusLabel(user: CompanyUser): string {
    return ({
      invited: 'Activation requested', active: 'Active', suspended: 'Suspended',
      provisioning_failed: 'Delivery failed', migration_required: 'Migration required',
    } as Record<string, string>)[user.auth_status] || 'Pending';
  }

  get filteredTimezones() { return filterTimezoneOptions(this.timezoneSearch); }
  get administrator(): CompanyUser | undefined { return this.users.find(user => user.role === 'admin'); }
  get teamUsers(): CompanyUser[] { return this.users.filter(user => user.role !== 'admin'); }
  roleLabel(role: CompanyUserRole): string { return ({ admin: 'Administrator', assistant: 'Assistant', mkt: 'Marketing', sales: 'Sales' })[role]; }
  projectName(projectId: string): string { return this.projects.find(item => item.id === projectId)?.name || 'Unavailable Project'; }
  isProjectSelected(projectId: string): boolean { return (this.invite.project_ids || []).includes(projectId); }
  toggleProject(projectId: string, selected: boolean): void {
    this.invite.project_ids = selected
      ? [...new Set([...(this.invite.project_ids || []), projectId])]
      : (this.invite.project_ids || []).filter(id => id !== projectId);
  }

  get formValid(): boolean {
    return !!(this.invite.first_name.trim() && this.invite.last_name.trim() &&
      /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(this.invite.email.trim()) &&
      ((this.invite.project_access_scope || 'all') === 'all' || (this.invite.project_ids || []).length > 0));
  }

  private emptyForm(): CompanyUserInvite {
    return { first_name: '', last_name: '', email: '', role: 'assistant', is_active: true,
      timezone: deviceTimezone(), project_access_scope: 'all', project_ids: [] };
  }
  private reloadLimits(): void { this.companyUsers.limits().subscribe({ next: limits => { this.limits = limits; this.cdr.markForCheck(); } }); }
}
