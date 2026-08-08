import { Component, OnInit, ChangeDetectorRef } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { TranslateModule } from '@ngx-translate/core';

import { AuthService } from '../../../../core/services/auth';
import { ToastService } from '../../../../core/services/toast';

import { GlassCardComponent } from '../../../../shared/ui/glass-card/glass-card';
import { InputComponent } from '../../../../shared/ui/input/input';
import { ButtonComponent } from '../../../../shared/ui/button/button';

@Component({
  selector: 'app-admin-profile-page',
  standalone: true,
  imports: [CommonModule, FormsModule, TranslateModule, GlassCardComponent, InputComponent, ButtonComponent],
  templateUrl: './profile-page.html'
})
export class ProfilePageComponent implements OnInit {
  user: any = {
    first_name: '',
    last_name: '',
    email: '',
    phone: '',
    country: ''
  };

  passForm = { current_password: '', new_password: '', confirm_password: '' };
  profileImageUrl: string = '';

  isLoading: boolean = true;
  isSaving: boolean = false;
  isChangingPass: boolean = false;

  constructor(
    private authService: AuthService,
    private toast: ToastService,
    private cdr: ChangeDetectorRef
  ) {}

  ngOnInit() {
    this.profileImageUrl = localStorage.getItem('bp_profile_image') || '';
    this.loadProfile();
  }

  onProfileImageSelected(event: Event) {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];

    if (!file) {
      return;
    }

    if (!file.type.startsWith('image/')) {
      this.toast.showError('Please upload an image file.');
      return;
    }

    const reader = new FileReader();
    reader.onload = () => {
      this.profileImageUrl = String(reader.result || '');
      localStorage.setItem('bp_profile_image', this.profileImageUrl);
      window.dispatchEvent(new Event('bp-profile-image-updated'));
      this.toast.showSuccess('Profile picture updated.');
      this.cdr.detectChanges();
    };
    reader.readAsDataURL(file);
  }

  loadProfile() {
    this.isLoading = true;
    this.authService.getMyProfile().subscribe({
      next: (data) => {
        // Aseguramos que los campos mapeen correctamente
        this.user = { 
          first_name: data.first_name || '',
          last_name: data.last_name || '',
          email: data.email || '',
          phone: data.phone || '',
          country: data.country || ''
        };
        this.isLoading = false;
        this.cdr.detectChanges();
      },
      error: () => {
        this.toast.showError('Error loading profile data.');
        this.isLoading = false;
        this.cdr.detectChanges();
      }
    });
  }

  saveProfile() {
    this.isSaving = true;
    this.cdr.detectChanges();

    this.authService.updateMyProfile(this.user).subscribe({
      next: () => {
        this.isSaving = false;
        this.toast.showSuccess('Profile updated successfully.');
        this.cdr.detectChanges();
      },
      error: (err) => {
        this.isSaving = false;
        this.toast.showError(err.error?.detail || 'Failed to update profile.');
        this.cdr.detectChanges();
      }
    });
  }

  changePassword() {
    if (this.passForm.new_password !== this.passForm.confirm_password) {
      this.toast.showError('New passwords do not match.');
      return;
    }

    this.isChangingPass = true;
    this.cdr.detectChanges();

    this.authService.changePassword({
      current_password: this.passForm.current_password,
      new_password: this.passForm.new_password
    }).subscribe({
      next: () => {
        this.isChangingPass = false;
        this.passForm = { current_password: '', new_password: '', confirm_password: '' };
        this.toast.showSuccess('Password updated successfully.');
        this.cdr.detectChanges();
      },
      error: (err) => {
        this.isChangingPass = false;
        this.toast.showError(err.error?.detail || 'Failed to update password.');
        this.cdr.detectChanges();
      }
    });
  }
}
