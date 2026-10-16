import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { API_V1_URL } from '../../../core/config/api.config';

export interface DashboardStats {
  projects: { active: number };
  leads: { current_month: number };
  ai_interactions: { current_month: number };
  generated_at: string;
  sales?: { assigned_leads: number; appointments_today: number; upcoming_appointments: number };
}

export type SetupStepId = 'company' | 'project' | 'availability' | 'lead';
export type SetupStepStatus = 'complete' | 'current' | 'locked';

export interface SetupProgressStep {
  id: SetupStepId;
  label: string;
  status: SetupStepStatus;
  url: string;
  entity_id: string | null;
  detail: string;
}

export interface SetupProgress {
  current_step: SetupStepId | 'complete';
  next_url: string;
  is_complete: boolean;
  steps: SetupProgressStep[];
}

@Injectable({ providedIn: 'root' })
export class DashboardService {
  constructor(private readonly http: HttpClient) {}
  getStats(): Observable<DashboardStats> { return this.http.get<DashboardStats>(`${API_V1_URL}/dashboard/stats`); }
  getSetupProgress(): Observable<SetupProgress> {
    return this.http.get<SetupProgress>(`${API_V1_URL}/dashboard/setup-progress`);
  }
}
