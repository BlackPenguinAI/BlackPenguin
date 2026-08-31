import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

import { API_V1_URL } from '../config/api.config';

export type CompanyUserRole = 'admin' | 'assistant' | 'mkt' | 'sales';
export type InvitableCompanyUserRole = Exclude<CompanyUserRole, 'admin'>;

export interface CompanyUser {
  id: string;
  email: string;
  first_name?: string;
  last_name?: string;
  role: CompanyUserRole;
  is_active: boolean;
  phone?: string;
  country?: string;
  timezone?: string;
  project_access_scope?: 'all' | 'selected';
  project_ids?: string[];
  project_assignment_required: boolean;
  auth_status: 'invited' | 'active' | 'suspended' | 'provisioning_failed' | 'migration_required';
  invitation_sent_at?: string;
  activated_at?: string;
}

export interface CompanyUserInvite {
  first_name: string;
  last_name: string;
  email: string;
  role: InvitableCompanyUserRole;
  is_active: boolean;
  timezone?: string;
  project_access_scope?: 'all' | 'selected';
  project_ids?: string[];
}

export interface CompanyUserUpdate extends Omit<CompanyUserInvite, 'email'> {}

export interface CompanyProjectOption { id: string; name: string; }

export type CompanyUserLimits = Record<InvitableCompanyUserRole, {
  used: number;
  limit: number;
}>;

@Injectable({ providedIn: 'root' })
export class CompanyUsersService {
  constructor(private readonly http: HttpClient) {}

  list(): Observable<CompanyUser[]> {
    return this.http.get<CompanyUser[]>(`${API_V1_URL}/users/company`);
  }

  limits(): Observable<CompanyUserLimits> {
    return this.http.get<CompanyUserLimits>(`${API_V1_URL}/users/company/limits`);
  }

  invite(payload: CompanyUserInvite): Observable<CompanyUser> {
    return this.http.post<CompanyUser>(`${API_V1_URL}/users/company`, payload);
  }

  projects(): Observable<CompanyProjectOption[]> {
    return this.http.get<CompanyProjectOption[]>(`${API_V1_URL}/users/company/projects`);
  }

  update(userId: string, payload: CompanyUserUpdate): Observable<CompanyUser> {
    return this.http.patch<CompanyUser>(`${API_V1_URL}/users/company/${userId}`, payload);
  }

  setActive(userId: string, isActive: boolean): Observable<CompanyUser> {
    return this.http.patch<CompanyUser>(`${API_V1_URL}/users/company/${userId}`, {
      is_active: isActive,
    });
  }

  resendActivation(userId: string): Observable<{ detail: string }> {
    return this.http.post<{ detail: string }>(
      `${API_V1_URL}/users/company/${userId}/resend-activation`,
      {},
    );
  }

  revokeInvitation(userId: string): Observable<{ detail: string }> {
    return this.http.delete<{ detail: string }>(
      API_V1_URL + '/users/company/' + userId + '/invitation',
    );
  }
}
