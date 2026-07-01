import { Component, AfterViewInit, ViewChild, ElementRef, HostListener } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterModule, Router } from '@angular/router';
import { TranslateModule, TranslateService } from '@ngx-translate/core';
import { AuthService } from '../../core/services/auth'; 
import { ToastService } from '../../core/services/toast'; // 🚀 Importamos

@Component({
  selector: 'app-register',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterModule, TranslateModule],
  templateUrl: './register.html',
  styleUrl: './register.scss'
})
export class RegisterComponent implements AfterViewInit {
  @ViewChild('bgVideo') bgVideo!: ElementRef<HTMLVideoElement>;

  // 🚀 Se añade fullName al objeto
  form = { fullName: '', email: '', password: '', confirmPassword: '' };
  isSubmitting = false;
  currentLang: string = 'en';

  constructor(
    private router: Router, 
    private translate: TranslateService, 
    private authService: AuthService,
    private toastService: ToastService // 🚀 Inyectamos
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
      next: (response) => {
        this.isSubmitting = false;
        this.toastService.showSuccess('Cuenta de administrador creada con éxito'); // 🚀 Éxito
        this.router.navigate(['/login']); 
      },
      error: (err) => {
        this.isSubmitting = false;
        this.toastService.showError(err.message); // 🚀 Muestra: "Este correo ya está registrado"
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