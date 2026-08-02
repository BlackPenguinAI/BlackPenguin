import { Injectable, isDevMode } from '@angular/core';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { Observable } from 'rxjs';

@Injectable({
  providedIn: 'root'
})
export class CompanyService {
  
  private get apiUrl(): string {
    return isDevMode() 
      ? 'http://localhost:8000/api/v1/companies/' 
      : 'https://blackpenguin.ai/api/v1/companies/';
  }

  private get headers(): HttpHeaders {
    const token = localStorage.getItem('bp_token');
    return new HttpHeaders().set('Authorization', `Bearer ${token}`);
  }

  constructor(private http: HttpClient) {}

  getCompanies(): Observable<any[]> {
    return this.http.get<any[]>(this.apiUrl, { headers: this.headers });
  }

  getPlans(): Observable<any[]> {
    const url = isDevMode() 
      ? 'http://localhost:8000/api/v1/plans/' 
      : 'https://blackpenguin.ai/api/v1/plans/';
    return this.http.get<any[]>(url, { headers: this.headers });
  }

  createCompany(formData: FormData): Observable<any> {
    return this.http.post<any>(this.apiUrl, formData, { headers: this.headers });
  }

  updateCompany(id: string, data: any): Observable<any> {
    return this.http.put<any>(`${this.apiUrl}${id}`, data, { headers: this.headers });
  }

  resendActivation(companyId: string): Observable<any> {
    return this.http.post<any>(`${this.apiUrl}${companyId}/resend-activation/`, {}, { headers: this.headers });
  }

  deleteCompany(companyId: string): Observable<any> {
    return this.http.delete<any>(`${this.apiUrl}${companyId}`, { headers: this.headers });
  }
}