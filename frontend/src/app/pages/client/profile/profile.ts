import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { AuthService } from '../../../core/services/auth';
import { ToastService } from '../../../core/services/toast';

@Component({
  selector: 'app-profile',
  standalone: true,
  imports: [CommonModule, FormsModule], // 🚀 Necesario para ngModel
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
    plan_name: 'Loading...',
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
    private toastService: ToastService
  ) {}

  ngOnInit(): void {
    this.loadProfile();
  }

  loadProfile() {
    this.authService.getMyProfile().subscribe({
      next: (data) => {
        this.profileData = { ...this.profileData, ...data };
        this.isLoading = false;
      },
      error: () => {
        this.toastService.showError('Error loading profile data');
        this.isLoading = false;
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
      },
      error: (err) => {
        this.toastService.showError('Could not update profile');
        this.isSaving = false;
      }
    });
  }

  updatePassword() {
    if (!this.passForm.current_password || !this.passForm.new_password) return;
    
    this.isChangingPass = true;
    this.authService.changePassword(this.passForm).subscribe({
      next: () => {
        this.toastService.showSuccess('Password updated successfully');
        this.passForm = { current_password: '', new_password: '' }; // Limpiar
        this.isChangingPass = false;
      },
      error: (err) => {
        this.toastService.showError('Incorrect current password');
        this.isChangingPass = false;
      }
    });
  }
}