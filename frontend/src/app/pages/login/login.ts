import { Component, AfterViewInit, OnDestroy, ViewChild, ElementRef } from '@angular/core';
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
export class LoginComponent implements AfterViewInit, OnDestroy {
  readonly backgroundVideoSrc = 'https://d8j0ntlcm91z4.cloudfront.net/user_38xzZboKViGWJOttwIXH07lWA1P/hf_20260403_050628_c4e32401-fab4-4a27-b7a8-6e9291cd5959.mp4';

  @ViewChild('bgVideo') bgVideo!: ElementRef<HTMLVideoElement>;
  
  credentials = { email: '', password: '' };
  rememberDevice = false;
  showPassword = false;
  isSubmitting = false;
  currentLang: string = 'en';
  private backgroundSegmentStart = 0;
  private backgroundSegmentEnd = 0;
  private backgroundTimeCheck?: number;

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
    const storedLang = localStorage.getItem('bp_lang');
    this.currentLang = storedLang === 'es' ? 'es' : 'en';
    
    // 3. Aplicamos el idioma y lo guardamos
    this.translate.use(this.currentLang);
    localStorage.setItem('bp_lang', this.currentLang);
  }

  switchLanguage(lang: string) {
    this.translate.use(lang);
    this.currentLang = lang;
    localStorage.setItem('bp_lang', lang);
  }

  ngAfterViewInit() {
    if (this.bgVideo?.nativeElement) {
      this.bgVideo.nativeElement.muted = true;
      this.syncBackgroundVideoSegment();
      this.bgVideo.nativeElement.play().catch(() => {});
    }
    this.backgroundTimeCheck = window.setInterval(() => this.syncBackgroundVideoSegment(), 60_000);
  }

  ngOnDestroy() {
    if (this.backgroundTimeCheck) {
      window.clearInterval(this.backgroundTimeCheck);
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

  togglePasswordVisibility() {
    this.showPassword = !this.showPassword;
  }

  private getSafeReturnUrl(userRole: string): string {
    const requestedUrl = this.route.snapshot.queryParamMap.get('returnUrl');
    const defaultUrl = userRole === 'superadmin' ? '/admin' : '/app';

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

  syncBackgroundVideoSegment() {
    const video = this.bgVideo?.nativeElement;
    if (!video || !Number.isFinite(video.duration) || video.duration <= 0) {
      return;
    }

    const segmentBoundary = video.duration / 2;
    const isClearSkyTime = this.isClearSkyTime(new Date());
    const nextStart = isClearSkyTime ? 0 : segmentBoundary;
    const nextEnd = isClearSkyTime ? segmentBoundary : video.duration;
    const segmentChanged = nextStart !== this.backgroundSegmentStart || nextEnd !== this.backgroundSegmentEnd;

    this.backgroundSegmentStart = nextStart;
    this.backgroundSegmentEnd = nextEnd;

    if (segmentChanged || video.currentTime < nextStart || video.currentTime >= nextEnd) {
      video.currentTime = nextStart;
    }
  }

  keepBackgroundInSelectedSegment() {
    const video = this.bgVideo?.nativeElement;
    if (!video || !this.backgroundSegmentEnd) {
      return;
    }

    if (video.currentTime >= this.backgroundSegmentEnd) {
      video.currentTime = this.backgroundSegmentStart;
      video.play().catch(() => {});
    }
  }

  private isClearSkyTime(now: Date): boolean {
    const minutes = now.getHours() * 60 + now.getMinutes();
    const clearSkyStart = 6 * 60;
    const clearSkyEnd = 17 * 60;

    return minutes >= clearSkyStart && minutes <= clearSkyEnd;
  }
}
