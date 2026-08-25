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

@Injectable({ providedIn: 'root' })
export class DashboardService {
  constructor(private readonly http: HttpClient) {}
  getStats(): Observable<DashboardStats> { return this.http.get<DashboardStats>(`${API_V1_URL}/dashboard/stats`); }
}
