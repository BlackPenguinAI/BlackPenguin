import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule, Router } from '@angular/router';
import { AuthService } from '../../core/services/auth';
import { TranslateModule, TranslateService } from '@ngx-translate/core';

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
    private translate: TranslateService
  ) {
    this.currentLang = localStorage.getItem('bp_lang') || 'en';
    this.translate.use(this.currentLang);
  }

  ngOnInit() {
    // 🚀 Sincronización de Rol al arrancar el contenedor maestro
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