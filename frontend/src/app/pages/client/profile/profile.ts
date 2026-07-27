import { Component, OnInit, ChangeDetectorRef } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { AuthService } from '../../../core/services/auth';
import { ToastService } from '../../../core/services/toast';

@Component({
  selector: 'app-profile',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './profile.html',
  styleUrls: ['./profile.scss']
})
export class ProfileComponent implements OnInit {
  isLoading: boolean = true;
  isSaving: boolean = false;
  isChangingPass: boolean = false;

  // Modelo de datos del perfil
  profileData = {
    email: '',
    full_name: '',
    last_name_paternal: '',
    last_name_maternal: '',
    company_name: '',
    plan_name: 'No active plan',
    license_start: null,
    license_end: null
  };

  // Modelo de datos del password
  passForm = {
    current_password: '',
    new_password: ''
  };

  constructor(
    private authService: AuthService,
    private toastService: ToastService,
    private cdr: ChangeDetectorRef // 🚀 Inyectamos ChangeDetectorRef para forzar el renderizado
  ) {}

  ngOnInit(): void {
    this.loadProfile();
  }

  loadProfile() {
    this.isLoading = true;
    this.authService.getMyProfile().subscribe({
      next: (data) => {
        this.profileData = { ...this.profileData, ...data };
        this.isLoading = false;
        this.cdr.detectChanges(); // 🚀 Obligamos a Angular a ocultar el spinner de inmediato
      },
      error: (err) => {
        this.toastService.showError('Error loading profile data');
        this.isLoading = false;
        this.cdr.detectChanges(); // 🚀 Obligamos a Angular a repintar en caso de error
      }
    });
  }

  saveProfile() {
    this.isSaving = true;
    const payload = {
      full_name: this.profileData.full_name,
      last_name_paternal: this.profileData.last_name_paternal,
      last_name_maternal: this.profileData.last_name_maternal,
      company_name: this.profileData.company_name
    };

    this.authService.updateMyProfile(payload).subscribe({
      next: () => {
        this.toastService.showSuccess('Profile updated successfully');
        this.isSaving = false;
        this.cdr.detectChanges();
      },
      error: (err) => {
        this.toastService.showError('Could not update profile');
        this.isSaving = false;
        this.cdr.detectChanges();
      }
    });
  }

  updatePassword() {
    if (!this.passForm.current_password || !this.passForm.new_password) return;
    
    this.isChangingPass = true;
    this.authService.changePassword(this.passForm).subscribe({
      next: () => {
        this.toastService.showSuccess('Password updated successfully');
        this.passForm = { current_password: '', new_password: '' };
        this.isChangingPass = false;
        this.cdr.detectChanges();
      },
      error: (err) => {
        this.toastService.showError('Incorrect current password');
        this.isChangingPass = false;
        this.cdr.detectChanges();
      }
    });
  }
}