import { Component, AfterViewInit, ViewChild, ElementRef, HostListener } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterModule, Router } from '@angular/router';
import { TranslateModule, TranslateService } from '@ngx-translate/core';
import { AuthService } from '../../core/services/auth'; 
import { ToastService } from '../../core/services/toast';

@Component({
  selector: 'app-register',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterModule, TranslateModule],
  templateUrl: './register.html',
  styleUrl: './register.scss'
})
export class RegisterComponent implements AfterViewInit {
  @ViewChild('bgVideo') bgVideo!: ElementRef<HTMLVideoElement>;

  form = { fullName: '', email: '', password: '', confirmPassword: '' };
  isSubmitting = false;
  currentLang: string = 'en';

  constructor(
    private router: Router, 
    private translate: TranslateService, 
    private authService: AuthService,
    private toastService: ToastService
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

  handleRegister() {
    if (this.form.password !== this.form.confirmPassword) return;

    this.isSubmitting = true;

    this.authService.registerAdmin(this.form).subscribe({
      // 🚀 SOLUCIÓN: Agregamos ": any" aquí
      next: (response: any) => {
        this.isSubmitting = false;
        this.toastService.showSuccess('Cuenta de administrador creada con éxito'); 
        this.router.navigate(['/login']); 
      },
      // 🚀 SOLUCIÓN: Agregamos ": any" aquí
      error: (err: any) => {
        this.isSubmitting = false;
        this.toastService.showError(err.message); 
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