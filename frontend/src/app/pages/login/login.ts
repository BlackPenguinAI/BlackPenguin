import { Component, AfterViewInit, ViewChild, ElementRef, HostListener } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterModule, Router } from '@angular/router';
import { TranslateModule, TranslateService } from '@ngx-translate/core';
import { AuthService } from '../../core/services/auth';
import { ToastService } from '../../core/services/toast';

@Component({
  selector: 'app-login',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterModule, TranslateModule],
  templateUrl: './login.html',
  styleUrl: './login.scss'
})
export class LoginComponent implements AfterViewInit {
  @ViewChild('bgVideo') bgVideo!: ElementRef<HTMLVideoElement>;
  
  credentials = { email: '', password: '' };
  isSubmitting = false;
  currentLang: string = 'en';

  constructor(
    private router: Router, 
    private route: ActivatedRoute,
    private translate: TranslateService, 
    private authService: AuthService,
    private toastService: ToastService
  ) {
    // 1. Configuramos los idiomas disponibles y el predeterminado
    this.translate.addLangs(['en', 'es']);
    this.translate.setDefaultLang('en');
    
    // 2. Buscamos si el usuario ya había elegido un idioma antes, si no, forzamos Inglés
    this.currentLang = 'en';
    
    // 3. Aplicamos el idioma y lo guardamos
    this.translate.use(this.currentLang);
    localStorage.setItem('bp_lang', this.currentLang);
  }

  switchLanguage(lang: string) {
    if (lang !== 'en') return;
    this.translate.use(lang);
    this.currentLang = lang;
    localStorage.setItem('bp_lang', lang);
  }

  ngAfterViewInit() {
    if (this.bgVideo?.nativeElement) {
      this.bgVideo.nativeElement.muted = true;
      this.bgVideo.nativeElement.play().catch(() => {});
    }
  }

  handleLogin() {
    this.isSubmitting = true;

    this.authService.login(this.credentials).subscribe({
      next: (response: any) => {
        this.isSubmitting = false;
        this.toastService.showSuccess('Access granted'); 
        
        // 🚀 Extraemos el rol procesado por el AuthService
        const userRole = response.role || localStorage.getItem('bp_role') || 'admin';

        const returnUrl = this.getSafeReturnUrl(userRole);
        void this.router.navigateByUrl(returnUrl, { replaceUrl: true });
      },
      error: (err) => {
        this.isSubmitting = false;
        this.toastService.showError(err.message); 
      }
    });
  }

  private getSafeReturnUrl(userRole: string): string {
    const requestedUrl = this.route.snapshot.queryParamMap.get('returnUrl');
    const defaultUrl = this.authService.defaultRouteForRole(userRole);

    if (!requestedUrl || !requestedUrl.startsWith('/') || requestedUrl.startsWith('//')) {
      return defaultUrl;
    }

    if (userRole === 'superadmin' && requestedUrl.startsWith('/admin')) {
      return requestedUrl;
    }

    if (userRole !== 'superadmin' && requestedUrl.startsWith('/app')) {
      return requestedUrl;
    }

    return defaultUrl;
  }

  @HostListener('document:mousemove', ['$event'])
  onMouseMove(e: MouseEvent) {
    if (this.bgVideo?.nativeElement) {
      const moveX = (e.clientX - window.innerWidth / 2) * 0.015;
      const moveY = (e.clientY - window.innerHeight / 2) * 0.015;
      this.bgVideo.nativeElement.style.transform = `scale(1.1) translate(${moveX}px, ${moveY}px)`;
    }
  }
}
