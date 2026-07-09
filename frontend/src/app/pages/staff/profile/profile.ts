import { Component, OnInit, isDevMode } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { TranslateModule, TranslateService } from '@ngx-translate/core';

@Component({
  selector: 'app-staff-profile',
  standalone: true,
  imports: [CommonModule, FormsModule, TranslateModule],
  templateUrl: './profile.html',
  styleUrl: './profile.scss'
})
export class StaffProfileComponent implements OnInit {
  user: any = {
    full_name: '',
    last_name_paternal: '',
    last_name_maternal: '',
    document_type: '',
    document_number: '',
    birth_date: '',
    email: '',
    phone: '',
    country: '',
    city: '',
    address: ''
  };

  isLoading: boolean = true;
  isSaving: boolean = false;
  statusMessage: string = '';
  isError: boolean = false;

  // Variables para Seguridad
  passForm = { current_password: '', new_password: '', confirm_password: '' };
  isChangingPass: boolean = false;
  passMessage: string = '';
  isPassError: boolean = false;

  constructor(private http: HttpClient, private translate: TranslateService) {}

  private get apiUrl() {
    return isDevMode() 
      ? 'http://localhost:8000/api/v1/auth/me' 
      : 'https://blackpenguin.ai/api/v1/auth/me';
  }

  private get headers() {
    const token = localStorage.getItem('bp_token');
    return new HttpHeaders().set('Authorization', `Bearer ${token}`);
  }

  ngOnInit() {
    this.loadProfile();
  }

  loadProfile() {
    this.isLoading = true;
    this.http.get<any>(this.apiUrl, { headers: this.headers }).subscribe({
      next: (data) => {
        this.user = data;
        this.isLoading = false;
      },
      error: () => {
        this.statusMessage = 'Error al cargar tu perfil.';
        this.isError = true;
        this.isLoading = false;
      }
    });
  }

  saveProfile() {
    this.isSaving = true;
    this.statusMessage = '';
    
    // No enviamos el email en el payload porque no es modificable
    const payload = { ...this.user };
    delete payload.email;
    delete payload.id;
    delete payload.role;

    this.http.put(this.apiUrl, payload, { headers: this.headers }).subscribe({
      next: () => {
        this.isSaving = false;
        this.isError = false;
        this.statusMessage = this.translate.instant('PROFILE_PAGE.MSG_SUCCESS') || '¡Perfil actualizado con éxito!';
        
        // Actualizar el nombre global si es que se cambió
        if (this.user.full_name) {
          localStorage.setItem('bp_name', this.user.full_name);
        }

        setTimeout(() => this.statusMessage = '', 4000);
      },
      error: () => {
        this.isSaving = false;
        this.isError = true;
        this.statusMessage = this.translate.instant('PROFILE_PAGE.MSG_ERROR') || 'Ocurrió un error al actualizar.';
      }
    });
  }

  // Función para cambiar contraseña
  changePassword() {
    if (this.passForm.new_password !== this.passForm.confirm_password) {
      this.isPassError = true;
      this.passMessage = this.translate.instant('PROFILE_PAGE.MSG_PASS_MISMATCH') || 'Las contraseñas nuevas no coinciden.';
      return;
    }

    this.isChangingPass = true;
    this.passMessage = '';

    const url = isDevMode() ? 'http://localhost:8000/api/v1/auth/change-password' : 'https://blackpenguin.ai/api/v1/auth/change-password';

    this.http.put(url, {
      current_password: this.passForm.current_password,
      new_password: this.passForm.new_password
    }, { headers: this.headers }).subscribe({
      next: () => {
        this.isChangingPass = false;
        this.isPassError = false;
        this.passMessage = this.translate.instant('PROFILE_PAGE.MSG_PASS_SUCCESS') || '¡Contraseña actualizada exitosamente!';
        this.passForm = { current_password: '', new_password: '', confirm_password: '' };
        setTimeout(() => this.passMessage = '', 4000);
      },
      error: (err) => {
        this.isChangingPass = false;
        this.isPassError = true;
        
        // Si el backend envía un error detallado (ej. "Contraseña actual incorrecta"), lo mostramos.
        // Si no, usamos el error genérico traducido.
        this.passMessage = err.error?.detail || this.translate.instant('PROFILE_PAGE.MSG_PASS_ERROR') || 'Error al cambiar la contraseña.';
      }
    });
  }
}