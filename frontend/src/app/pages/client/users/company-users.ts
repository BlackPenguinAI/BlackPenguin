import { CommonModule } from '@angular/common';
import { ChangeDetectorRef, Component, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { forkJoin } from 'rxjs';

import {
  CompanyProjectOption, CompanyUser, CompanyUserInvite, CompanyUserLimits,
  CompanyUserRole, CompanyUsersService,
} from '../../../core/services/company-users.service';
import { deviceTimezone, timezoneLabel } from '../../../core/timezones';
import { ToastService } from '../../../core/services/toast';
import { ButtonComponent } from '../../../shared/ui/button/button';
import { InputComponent } from '../../../shared/ui/input/input';
import { ModalComponent } from '../../../shared/ui/modal/modal';
import { TimezoneSelectComponent } from '../../../shared/ui/timezone-select/timezone-select';

@Component({
  selector: 'app-company-users', standalone: true,
  imports: [CommonModule, FormsModule, ButtonComponent, InputComponent, ModalComponent, TimezoneSelectComponent],
  templateUrl: './company-users.html',
})
export class CompanyUsersComponent implements OnInit {
  users: CompanyUser[] = [];
  projects: CompanyProjectOption[] = [];
  limits: CompanyUserLimits | null = null;
  loading = true; saving = false; showAddModal = false;
  editingUserId: string | null = null;
  invite: CompanyUserInvite = this.emptyForm();
  readonly timezoneLabel = timezoneLabel;
  private inviteRequestKey = '';
  private inviteRequestFingerprint = '';

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
    this.inviteRequestKey = ''; this.inviteRequestFingerprint = '';
    this.showAddModal = true;
  }

  openEditModal(user: CompanyUser): void {
    this.editingUserId = user.id;
    this.invite = {
      first_name: user.first_name || '', last_name: user.last_name || '', email: user.email,
      role: user.role === 'admin' ? 'assistant' : user.role, is_active: user.is_active,
      timezone: user.timezone || deviceTimezone(), project_access_scope: user.project_access_scope || 'all',
      project_ids: [...(user.project_ids || [])],
    };
    this.showAddModal = true;
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
      : this.companyUsers.invite(this.invite, this.invitationRequestKey());
    request.subscribe({
      next: user => {
        const index = this.users.findIndex(item => item.id === user.id);
        this.users = index < 0 ? [...this.users, user] : this.users.map(item => item.id === user.id ? user : item);
        this.users.sort((a, b) => a.email.localeCompare(b.email));
        this.showAddModal = false; this.saving = false;
        this.inviteRequestKey = ''; this.inviteRequestFingerprint = '';
        const message = this.invitationResultMessage(user);
        if (!this.editingUserId && (user.invitation_delivery === 'failed' || user.auth_status === 'provisioning_failed')) {
          this.toast.showError(message);
        } else {
          this.toast.showSuccess(this.editingUserId ? 'User updated' : message);
        }
        this.reloadLimits(); this.cdr.markForCheck();
      },
      error: err => {
        this.saving = false;
        const detail = err.error?.detail;
        this.toast.showError(typeof detail === 'string' ? detail : detail?.message || 'Could not save user');
        if (detail?.code === 'USER_ALREADY_INVITED') this.load();
        this.cdr.markForCheck();
      },
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
      error: err => {
        const detail = err.error?.detail;
        this.toast.showError(typeof detail === 'string' ? detail : detail?.message || 'Could not resend activation');
      },
    });
  }

  authStatusLabel(user: CompanyUser): string {
    if (user.invitation_error_code === 'QUOTA_EXCEEDED') return 'Email quota exceeded';
    return ({
      invited: 'Activation requested', active: 'Active', suspended: 'Suspended',
      provisioning_failed: 'Delivery failed', migration_required: 'Migration required',
    } as Record<string, string>)[user.auth_status] || 'Pending';
  }

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
  private invitationRequestKey(): string {
    const fingerprint = JSON.stringify({
      ...this.invite,
      first_name: this.invite.first_name.trim(), last_name: this.invite.last_name.trim(),
      email: this.invite.email.trim().toLowerCase(),
      project_ids: [...(this.invite.project_ids || [])].sort(),
    });
    if (!this.inviteRequestKey || fingerprint !== this.inviteRequestFingerprint) {
      const random = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`;
      this.inviteRequestKey = `company-user-${random}`;
      this.inviteRequestFingerprint = fingerprint;
    }
    return this.inviteRequestKey;
  }
  private invitationResultMessage(user: CompanyUser): string {
    if (user.request_replayed) return `The invitation for ${user.email} was already processed.`;
    if (user.invitation_delivery === 'failed' || user.auth_status === 'provisioning_failed') {
      if (user.invitation_error_message) return `User ${user.email} was saved. ${user.invitation_error_message}`;
      const code = user.invitation_error_code ? ` (${user.invitation_error_code})` : '';
      return `User saved, but Firebase did not accept the invitation for ${user.email}${code}.`;
    }
    return `Invitation sent to ${user.email}. The user is pending activation.`;
  }
  private reloadLimits(): void { this.companyUsers.limits().subscribe({ next: limits => { this.limits = limits; this.cdr.markForCheck(); } }); }
}
