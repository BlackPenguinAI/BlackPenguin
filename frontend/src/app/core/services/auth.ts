import { Injectable, isDevMode } from '@angular/core'; // 🚀 IMPORTANTE: Añadir isDevMode
import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable, tap, catchError, throwError } from 'rxjs';

@Injectable({
  providedIn: 'root'
})
export class AuthService {
  
  // 🚀 URL DINÁMICA: Local vs Producción
  private apiUrl = isDevMode() 
    ? 'http://localhost:8000/api/v1' 
    : 'http://206.189.118.99:8000/api/v1';

  constructor(private http: HttpClient) {}

  registerAdmin(userData: any): Observable<any> {
    const payload = {
      full_name: userData.fullName, // 🚀 Añadimos el nombre al payload
      email: userData.email,
      password: userData.password,
      role: 'admin',
      is_active: true
    };
    
    return this.http.post(`${this.apiUrl}/auth/register`, payload).pipe(
      catchError(this.handleError)
    );
  }

  login(credentials: any): Observable<any> {
    const formData = new URLSearchParams();
    formData.set('username', credentials.email); 
    formData.set('password', credentials.password);

    return this.http.post(`${this.apiUrl}/auth/login`, formData.toString(), {
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' }
    }).pipe(
      tap((response: any) => {
        if (response && response.access_token) {
          localStorage.setItem('bp_token', response.access_token);
          // 🚀 Si el backend nos manda el nombre, lo guardamos
          if (response.name) {
            localStorage.setItem('bp_name', response.name); 
          }
        }
      }),
      catchError(this.handleError)
    );
  }

  logout() {
    localStorage.removeItem('bp_token');
    localStorage.removeItem('bp_name'); // Limpiamos el nombre al salir
  }

  getToken(): string | null {
    return localStorage.getItem('bp_token');
  }

  private handleError(error: any) {
    console.error('Error en AuthService:', error);
    return throwError(() => new Error(error.error?.detail || 'Error de conexión con el servidor.'));
  }
}