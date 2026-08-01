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
      this.cdr.detectChanges();
    });
  }

  ngOnInit() {
    this.userRole = localStorage.getItem('bp_role') || '';
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
}