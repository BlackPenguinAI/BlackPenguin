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
}

export interface CompanyUserInvite {
  first_name: string;
  last_name: string;
  email: string;
  role: InvitableCompanyUserRole;
  password: string;
  is_active: boolean;
}

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
}
