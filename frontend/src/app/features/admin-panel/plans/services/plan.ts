import { Injectable, isDevMode } from '@angular/core';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { Observable } from 'rxjs';

@Injectable({
  providedIn: 'root'
})
export class PlanService {
  
  private get apiUrl(): string {
    return isDevMode() 
      ? 'http://localhost:8000/api/v1/plans/' 
      : 'https://blackpenguin.ai/api/v1/plans/';
  }

  private get headers(): HttpHeaders {
    const token = localStorage.getItem('bp_token');
    return new HttpHeaders().set('Authorization', `Bearer ${token}`);
  }

  constructor(private http: HttpClient) {}

  getPlans(): Observable<any[]> {
    return this.http.get<any[]>(this.apiUrl, { headers: this.headers });
  }

  createPlan(data: any): Observable<any> {
    return this.http.post<any>(this.apiUrl, data, { headers: this.headers });
  }

  // 🚀 NUEVO: ACTUALIZAR PLAN
  updatePlan(id: string, data: any): Observable<any> {
    return this.http.put<any>(`${this.apiUrl}${id}/`, data, { headers: this.headers });
  }

  // 🚀 CORREGIDO: SE AGREGÓ LA BARRA AL FINAL
  deletePlan(id: string): Observable<any> {
    return this.http.delete<any>(`${this.apiUrl}${id}/`, { headers: this.headers });
  }
}