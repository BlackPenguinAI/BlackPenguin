import { Component, AfterViewInit, ViewChild, ElementRef, HostListener } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterModule, Router } from '@angular/router';
import { TranslateModule, TranslateService } from '@ngx-translate/core';
import { AuthService } from '../../core/services/auth';
import { ToastService } from '../../core/services/toast'; // 🚀 Importamos el Toast

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
    private translate: TranslateService, 
    private authService: AuthService,
    private toastService: ToastService // 🚀 Inyectamos el servicio
  ) {
    this.currentLang = this.translate.currentLang || localStorage.getItem('bp_lang') || 'en';
  }

  switchLanguage(lang: string) {
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
      next: (response) => {
        this.isSubmitting = false;
        this.toastService.showSuccess('Access granted'); // 🚀 Notificación de éxito
        this.router.navigate(['/chat']); 
      },
      error: (err) => {
        this.isSubmitting = false;
        this.toastService.showError(err.message); // 🚀 Muestra el error exacto del backend (ej: Contraseña incorrecta)
      }
    });
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