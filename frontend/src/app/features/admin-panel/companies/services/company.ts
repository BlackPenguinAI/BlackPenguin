import { Injectable, isDevMode } from '@angular/core';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { Observable } from 'rxjs';

@Injectable({
  providedIn: 'root'
})
export class CompanyService {
  
  // 🚀 AÑADIMOS LA BARRA FINAL PARA EVITAR EL REDIRECT 307 DE FASTAPI
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

  // 1. Listar todas las empresas con sus planes
  getCompanies(): Observable<any[]> {
    return this.http.get<any[]>(this.apiUrl, { headers: this.headers });
  }

  // 2. Listar planes disponibles para el selector
  getPlans(): Observable<any[]> {
    // 🚀 AÑADIMOS LA BARRA FINAL AQUÍ TAMBIÉN
    const url = isDevMode() 
      ? 'http://localhost:8000/api/v1/plans/' 
      : 'https://blackpenguin.ai/api/v1/plans/';
    return this.http.get<any[]>(url, { headers: this.headers });
  }

  // 3. Crear empresa con administrador y comprobante (FormData / Multipart)
  createCompany(formData: FormData): Observable<any> {
    return this.http.post<any>(this.apiUrl, formData, { headers: this.headers });
  }

  // 4. Reenviar enlace de activación
  resendActivation(companyId: string): Observable<any> {
    // Como apiUrl ya termina en '/', concatenamos directamente el ID
    return this.http.post<any>(`${this.apiUrl}${companyId}/resend-activation/`, {}, { headers: this.headers });
  }

  // 5. Eliminar empresa
  deleteCompany(companyId: string): Observable<any> {
    return this.http.delete<any>(`${this.apiUrl}${companyId}/`, { headers: this.headers });
  }
}