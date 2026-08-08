import { Component, OnInit, OnDestroy, ChangeDetectorRef } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule, Router, NavigationEnd } from '@angular/router';
import { AuthService } from '../../core/services/auth';
import { TranslateModule, TranslateService } from '@ngx-translate/core';
import { filter } from 'rxjs/operators';

@Component({
  selector: 'app-layout',
  standalone: true,
  imports: [CommonModule, RouterModule, TranslateModule],
  templateUrl: './layout.html',
  styleUrl: './layout.scss'
})
export class LayoutComponent implements OnInit, OnDestroy {
  userRole: string = '';
  currentLang: string = 'en';
  displayName: string = 'Local User';
  userEmail: string = 'local@blackpenguin.ai';
  profileImageUrl: string = '';

  constructor(
    private router: Router, 
    private authService: AuthService,
    private translate: TranslateService,
    private cdr: ChangeDetectorRef
  ) {
    this.currentLang = localStorage.getItem('bp_lang') || 'en';
    this.translate.use(this.currentLang);

    // Escuchamos los cambios de ruta para refrescar el rol del usuario dinámicamente
    this.router.events.pipe(
      filter(event => event instanceof NavigationEnd)
    ).subscribe(() => {
      this.userRole = localStorage.getItem('bp_role') || '';
      this.profileImageUrl = localStorage.getItem('bp_profile_image') || '';
      this.cdr.detectChanges();
    });
  }

  ngOnInit() {
    this.userRole = localStorage.getItem('bp_role') || '';
    this.refreshUserSummary();
    window.addEventListener('bp-profile-image-updated', this.handleProfileImageUpdated);
    this.authService.getMyProfile().subscribe({
      next: (user) => {
        const firstName = user?.first_name || '';
        const lastName = user?.last_name || '';
        const fullName = `${firstName} ${lastName}`.trim();

        this.displayName = fullName || user?.name || localStorage.getItem('bp_name') || this.displayName;
        this.userEmail = user?.email || this.userEmail;
        this.cdr.detectChanges();
      },
      error: () => {
        this.refreshUserSummary();
      }
    });
  }

  ngOnDestroy() {
    window.removeEventListener('bp-profile-image-updated', this.handleProfileImageUpdated);
  }

  get profileRoute(): string {
    return this.userRole === 'superadmin' ? '/admin/profile' : '/app/profile';
  }

  get userInitials(): string {
    const parts = this.displayName.trim().split(/\s+/).filter(Boolean);
    const initials = parts.slice(0, 2).map((part) => part[0]).join('');
    return (initials || this.userEmail[0] || 'U').toUpperCase();
  }

  switchLanguage(lang: string) {
    this.translate.use(lang);
    this.currentLang = lang;
    localStorage.setItem('bp_lang', lang);
  }

  logout() {
    this.authService.logout();
    this.router.navigate(['/login']);
  }

  private refreshUserSummary() {
    this.displayName = localStorage.getItem('bp_name') || this.displayName;
    this.userEmail = this.getTokenEmail() || this.userEmail;
    this.profileImageUrl = localStorage.getItem('bp_profile_image') || '';
  }

  private handleProfileImageUpdated = () => {
    this.profileImageUrl = localStorage.getItem('bp_profile_image') || '';
    this.cdr.detectChanges();
  };

  private getTokenEmail(): string | null {
    const token = this.authService.getToken();
    if (!token) {
      return null;
    }

    try {
      const [, payload] = token.split('.');
      const base64 = payload.replace(/-/g, '+').replace(/_/g, '/');
      const padded = base64.padEnd(Math.ceil(base64.length / 4) * 4, '=');
      return JSON.parse(atob(padded))?.sub || null;
    } catch {
      return null;
    }
  }
}
