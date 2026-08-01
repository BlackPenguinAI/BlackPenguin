import { Injectable, isDevMode } from '@angular/core';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { Observable } from 'rxjs';

@Injectable({
  providedIn: 'root'
})
export class DashboardService {
  
  private get apiUrl(): string {
    return isDevMode() 
      ? 'http://localhost:8000/api/v1/system/stats/' 
      : 'https://blackpenguin.ai/api/v1/system/stats/';
  }

  private get headers(): HttpHeaders {
    const token = localStorage.getItem('bp_token');
    return new HttpHeaders().set('Authorization', `Bearer ${token}`);
  }

  constructor(private http: HttpClient) {}

  getAdminStats(): Observable<any> {
    return this.http.get<any>(this.apiUrl, { headers: this.headers });
  }
}