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
}