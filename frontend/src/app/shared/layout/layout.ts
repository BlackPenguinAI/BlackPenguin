import { Component, OnInit, ChangeDetectorRef } from '@angular/core';
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
export class LayoutComponent implements OnInit {
  userRole: string = '';
  currentLang: string = 'en';
  profile: any = null;

  constructor(
    private router: Router, 
    private authService: AuthService,
    private translate: TranslateService,
    private cdr: ChangeDetectorRef
  ) {
    this.currentLang = 'en';
    this.translate.use(this.currentLang);
    if (typeof localStorage !== 'undefined') localStorage.setItem('bp_lang', 'en');

    // Escuchamos los cambios de ruta para refrescar el rol del usuario dinámicamente
    this.router.events.pipe(
      filter(event => event instanceof NavigationEnd)
    ).subscribe(() => {
      this.userRole = typeof localStorage === 'undefined' ? '' : localStorage.getItem('bp_role') || '';
      this.cdr.detectChanges();
    });
  }

  ngOnInit() {
    this.userRole = typeof localStorage === 'undefined' ? '' : localStorage.getItem('bp_role') || '';
    this.authService.getMyProfile().subscribe({
      next: profile => { this.profile = profile; this.userRole = profile.role || this.userRole; this.cdr.detectChanges(); },
      error: () => { this.profile = null; this.cdr.detectChanges(); },
    });
  }

  switchLanguage(lang: string) {
    if (lang !== 'en') return;
    this.translate.use(lang);
    this.currentLang = lang;
    if (typeof localStorage !== 'undefined') localStorage.setItem('bp_lang', lang);
  }

  get displayName(): string {
    return [this.profile?.first_name, this.profile?.last_name].filter(Boolean).join(' ') || this.profile?.email || 'Black Penguin user';
  }

  get roleLabel(): string {
    return ({ superadmin: 'Black Penguin Administrator', admin: 'Company Administrator', assistant: 'Assistant', mkt: 'Marketing', sales: 'Sales' } as Record<string, string>)[this.userRole] || this.userRole;
  }

  get identityScope(): string {
    return this.userRole === 'superadmin' ? 'Black Penguin Platform' : (this.profile?.company_name || 'Company workspace');
  }

  get initials(): string {
    const source = this.displayName.split(/\s+/).filter(Boolean);
    return source.slice(0, 2).map(value => value[0]?.toUpperCase()).join('') || 'BP';
  }

  logout() {
    this.authService.logout();
    this.router.navigate(['/login']);
  }
}
