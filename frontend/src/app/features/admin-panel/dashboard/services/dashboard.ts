import { Injectable, isDevMode } from '@angular/core';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { Observable, of } from 'rxjs';
import { catchError } from 'rxjs/operators';

@Injectable({
  providedIn: 'root'
})
export class DashboardService {
  
  private get apiUrl(): string {
    return isDevMode() 
      ? 'http://localhost:8000/api/v1/system/stats' 
      : 'https://blackpenguin.ai/api/v1/system/stats';
  }

  private get headers(): HttpHeaders {
    const token = localStorage.getItem('bp_token');
    return new HttpHeaders().set('Authorization', `Bearer ${token}`);
  }

  constructor(private http: HttpClient) {}

  getAdminStats(): Observable<any> {
    return this.http.get<any>(this.apiUrl, { headers: this.headers }).pipe(
      // 🚀 SALVAVIDAS: Atrapa el error 404 y devuelve datos en cero para no romper la UI
      catchError(err => {
        console.warn('⚠️ Endpoint de stats no programado en backend. Usando ceros.');
        return of({
          total_companies: 0,
          active_companies: 0,
          total_projects: 0,
          total_waitlist: 0,
          total_users: 0,
          system_status: 'API Pending'
        });
      })
    );
  }
}