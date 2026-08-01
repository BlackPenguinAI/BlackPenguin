import { Injectable, isDevMode } from '@angular/core';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { Observable } from 'rxjs';

@Injectable({
  providedIn: 'root'
})
export class PlanService {
  
  private get apiUrl(): string {
    return isDevMode() 
      ? 'http://localhost:8000/api/v1/plans' 
      : 'https://blackpenguin.ai/api/v1/plans';
  }

  private get headers(): HttpHeaders {
    const token = localStorage.getItem('bp_token');
    return new HttpHeaders().set('Authorization', `Bearer ${token}`);
  }

  constructor(private http: HttpClient) {}

  getPlans(): Observable<any[]> {
    return this.http.get<any[]>(this.apiUrl, { headers: this.headers });
  }

  createPlan(planData: any): Observable<any> {
    return this.http.post<any>(this.apiUrl, planData, { headers: this.headers });
  }

  deletePlan(planId: string): Observable<any> {
    return this.http.delete<any>(`${this.apiUrl}/${planId}`, { headers: this.headers });
  }
}