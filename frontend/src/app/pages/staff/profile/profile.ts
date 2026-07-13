import { Component, OnInit, isDevMode, ChangeDetectorRef } from '@angular/core'; 
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

  passForm = { current_password: '', new_password: '', confirm_password: '' };
  isChangingPass: boolean = false;
  passMessage: string = '';
  isPassError: boolean = false;

  constructor(
    private http: HttpClient, 
    private translate: TranslateService,
    private cdr: ChangeDetectorRef // 🚀 Control directo del renderizado
  ) {}

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
    this.cdr.detectChanges(); // Mostrar spinner

    this.http.get<any>(this.apiUrl, { headers: this.headers }).subscribe({
      next: (data) => {
        this.user = data;
        this.isLoading = false;
        this.cdr.detectChanges(); // 🚀 Mostrar datos en cuanto llegan
      },
      error: (err) => {
        console.error('❌ Error cargando perfil:', err);
        this.isLoading = false;
        this.cdr.detectChanges();
      }
    });
  }

  saveProfile() {
    this.isSaving = true;
    this.statusMessage = '';
    this.cdr.detectChanges();

    this.http.put<any>(this.apiUrl, {
      full_name: this.user.full_name,
      last_name_paternal: this.user.last_name_paternal,
      last_name_maternal: this.user.last_name_maternal,
      document_type: this.user.document_type,
      document_number: this.user.document_number,
      birth_date: this.user.birth_date,
      phone: this.user.phone,
      country: this.user.country,
      city: this.user.city,
      address: this.user.address
    }, { headers: this.headers }).subscribe({
      next: (updatedData) => {
        this.user = updatedData;
        this.isSaving = false;
        this.isError = false;
        this.statusMessage = this.translate.instant('PROFILE_PAGE.MSG_SAVE_SUCCESS') || '¡Perfil actualizado exitosamente!';
        this.cdr.detectChanges();
        
        setTimeout(() => {
          this.statusMessage = '';
          this.cdr.detectChanges();
        }, 4000);
      },
      error: (err) => {
        this.isSaving = false;
        this.isError = true;
        this.statusMessage = err.error?.detail || this.translate.instant('PROFILE_PAGE.MSG_SAVE_ERROR') || 'Error al guardar los cambios.';
        this.cdr.detectChanges();
      }
    });
  }

  changePassword() {
    if (this.passForm.new_password !== this.passForm.confirm_password) {
      this.isPassError = true;
      this.passMessage = this.translate.instant('PROFILE_PAGE.MSG_PASS_MISMATCH') || 'Las contraseñas nuevas no coinciden.';
      return;
    }

    this.isChangingPass = true;
    this.passMessage = '';
    this.cdr.detectChanges();

    const url = isDevMode() 
      ? 'http://localhost:8000/api/v1/auth/change-password' 
      : 'https://blackpenguin.ai/api/v1/auth/change-password';

    this.http.put(url, {
      current_password: this.passForm.current_password,
      new_password: this.passForm.new_password
    }, { headers: this.headers }).subscribe({
      next: () => {
        this.isChangingPass = false;
        this.isPassError = false;
        this.passMessage = this.translate.instant('PROFILE_PAGE.MSG_PASS_SUCCESS') || '¡Contraseña actualizada exitosamente!';
        this.passForm = { current_password: '', new_password: '', confirm_password: '' };
        this.cdr.detectChanges();
        
        setTimeout(() => {
          this.passMessage = '';
          this.cdr.detectChanges();
        }, 4000);
      },
      error: (err) => {
        this.isChangingPass = false;
        this.isPassError = true;
        this.passMessage = err.error?.detail || this.translate.instant('PROFILE_PAGE.MSG_PASS_ERROR') || 'No se pudo actualizar la contraseña. Revisa tus datos.';
        this.cdr.detectChanges();
      }
    });
  }
}