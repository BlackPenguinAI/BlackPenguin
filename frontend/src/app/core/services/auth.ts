import { Injectable, isDevMode } from '@angular/core'; 
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { Observable, tap, catchError, throwError } from 'rxjs';

@Injectable({
  providedIn: 'root'
})
export class AuthService {
  
  private apiUrl = isDevMode() 
    ? 'http://localhost:8000/api/v1' 
    : 'https://blackpenguin.ai/api/v1';

  constructor(private http: HttpClient) {}

  registerAdmin(userData: any): Observable<any> {
    const payload = {
      full_name: userData.fullName, 
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
          
          const role = response.role || 'admin';
          localStorage.setItem('bp_role', role);
          
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
    localStorage.removeItem('bp_role');
    localStorage.removeItem('bp_name'); 
  }

  getToken(): string | null {
    return localStorage.getItem('bp_token');
  }

  hasValidToken(): boolean {
    const token = this.getToken();
    if (!token) return false;

    try {
      const parts = token.split('.');
      if (parts.length !== 3) return false;

      const base64 = parts[1].replace(/-/g, '+').replace(/_/g, '/');
      const padded = base64.padEnd(Math.ceil(base64.length / 4) * 4, '=');
      const payload = JSON.parse(atob(padded));

      return typeof payload.exp === 'number' && payload.exp * 1000 > Date.now();
    } catch {
      return false;
    }
  }

  private handleError(error: any) {
    console.error('Error en AuthService:', error);
    return throwError(() => new Error(error.error?.detail || 'Error en la autenticación.'));
  }

  // Helper para inyectar el token en las peticiones seguras
  private getHeaders() {
    const token = this.getToken();
    return { headers: new HttpHeaders({ 'Authorization': `Bearer ${token}` }) };
  }

  // 1. Obtener Perfil Completo
  getMyProfile(): Observable<any> {
    return this.http.get(`${this.apiUrl}/users/me`, this.getHeaders()).pipe(
      catchError(this.handleError)
    );
  }

  // 2. Actualizar Perfil
  updateMyProfile(profileData: any): Observable<any> {
    return this.http.put(`${this.apiUrl}/users/me`, profileData, this.getHeaders()).pipe(
      catchError(this.handleError)
    );
  }

  // 3. Cambiar Contraseña
  changePassword(data: any): Observable<any> {
    // 🚀 OJO AQUÍ: Debe terminar en /change-password/
    return this.http.put(`${this.apiUrl}/auth/change-password/`, data, this.getHeaders()).pipe(
      catchError(this.handleError)
    );
  }

}
