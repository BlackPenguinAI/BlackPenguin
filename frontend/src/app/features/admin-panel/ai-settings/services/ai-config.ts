import { Injectable, isDevMode } from '@angular/core';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { Observable } from 'rxjs';

@Injectable({
  providedIn: 'root'
})
export class AiConfigService {
  
  // 🚀 Apunta a nuestro nuevo Micro-Módulo del Backend (ai_core)
  private get apiUrl(): string {
    return isDevMode() 
      ? 'http://localhost:8000/api/v1/ai' 
      : 'https://blackpenguin.ai/api/v1/ai';
  }

  private get headers(): HttpHeaders {
    const token = localStorage.getItem('bp_token');
    return new HttpHeaders().set('Authorization', `Bearer ${token}`);
  }

  constructor(private http: HttpClient) {}

  getConfig(): Observable<any> {
    return this.http.get<any>(`${this.apiUrl}/config`, { headers: this.headers });
  }

  updateConfig(payload: any): Observable<any> {
    return this.http.put<any>(`${this.apiUrl}/config`, payload, { headers: this.headers });
  }

  getConsumption(): Observable<any> {
    return this.http.get<any>(`${this.apiUrl}/config/consumption`, { headers: this.headers });
  }
}