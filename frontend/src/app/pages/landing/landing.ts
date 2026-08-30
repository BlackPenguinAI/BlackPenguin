import { Component, AfterViewInit, ViewChild, ElementRef, ViewChildren, QueryList, HostListener, isDevMode, ChangeDetectorRef } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterModule } from '@angular/router'; 
import { TranslateModule, TranslateService } from '@ngx-translate/core';
import { HttpClient } from '@angular/common/http'; 

@Component({
  selector: 'app-landing',
  standalone: true,
  imports: [CommonModule, FormsModule, TranslateModule, RouterModule],
  templateUrl: './landing.html',
  styleUrl: './landing.scss'
})
export class LandingComponent implements AfterViewInit {
  email: string = '';
  isSubmitting: boolean = false;
  showSuccess: boolean = false;
  errorMessage: string = ''; 
  currentLang: string = 'en';
  isMobileMenuOpen: boolean = false;

  @ViewChild('bgVideo') bgVideo!: ElementRef<HTMLVideoElement>;
  @ViewChild('heroHeading') heroHeading!: ElementRef<HTMLHeadingElement>;
  @ViewChild('statusRow') statusRow!: ElementRef<HTMLDivElement>;
  @ViewChild('heroSubheading') heroSubheading!: ElementRef<HTMLParagraphElement>;
  @ViewChild('heroCta') heroCta!: ElementRef<HTMLDivElement>;
  @ViewChildren('featureCard') featureCards!: QueryList<ElementRef<HTMLDivElement>>;

  constructor(
    private translate: TranslateService,
    private http: HttpClient,
    private cdr: ChangeDetectorRef // 🚀 NUEVO: Inyectamos el actualizador de vista
  ) {
    this.currentLang = 'en'; this.translate.use('en');
    if (typeof localStorage !== 'undefined') localStorage.setItem('bp_lang', 'en');
  }

  switchLanguage(lang: string) {
    if (lang !== 'en') return;
    this.translate.use(lang);
    this.currentLang = lang;
    localStorage.setItem('bp_lang', lang);
  }

  toggleMobileMenu() {
    this.isMobileMenuOpen = !this.isMobileMenuOpen;
  }

  // 🚀 FUNCIÓN AÑADIDA: Permite deslizarse suavemente por las secciones del Landing
  scrollToSection(sectionId: string) {
    const element = document.getElementById(sectionId);
    if (element) {
      element.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  }

  ngAfterViewInit() {
    if (this.bgVideo?.nativeElement) {
      this.bgVideo.nativeElement.muted = true;
      this.bgVideo.nativeElement.play().catch(() => {});
    }
    this.triggerFadeIns();
    this.setupScrollObserver();
  }

  joinWaitlist() {
    if (!this.email) return;

    this.isSubmitting = true;
    this.errorMessage = '';

    const apiUrl = isDevMode() 
      ? 'http://localhost:8000/api/v1/waitlist/' 
      : 'https://blackpenguin.ai/api/v1/waitlist/';

    const payload = { 
      email: this.email, 
      language: this.currentLang 
    };

    this.http.post(apiUrl, payload).subscribe({
      next: () => {
        this.isSubmitting = false;
        this.showSuccess = true;
        this.email = ''; 
        this.cdr.detectChanges(); // 🚀 Obligamos a renderizar el éxito
        
        setTimeout(() => this.showSuccess = false, 5000);
      },
      error: (err) => {
        this.isSubmitting = false;
        
        // 🚀 MAPEO DE ERRORES CON TRADUCCIÓN (Inglés por defecto como fallback)
        if (err.status === 400) {
          // Captura el error de duplicado (400)
          this.errorMessage = this.translate.instant('LANDING.WAITLIST_DUPLICATE') || 'This email is already on the waitlist.';
        } else {
          // Captura cualquier otro error de servidor (500, etc)
          this.errorMessage = this.translate.instant('LANDING.WAITLIST_ERROR') || 'An error occurred. Please try again.';
        }
        
        this.cdr.detectChanges(); // 🚀 OBLIGAMOS A ANGULAR A MOSTRAR EL ERROR
        
        setTimeout(() => this.errorMessage = '', 5000);
      }
    });
  }

  private triggerFadeIns() {
    setTimeout(() => this.statusRow.nativeElement.classList.add('visible'), 100);
    setTimeout(() => this.heroSubheading.nativeElement.classList.add('visible'), 1000);
    setTimeout(() => this.heroCta.nativeElement.classList.add('visible'), 1300);
  }

  private setupScrollObserver() {
    const observer = new IntersectionObserver((entries) => {
      entries.forEach(entry => {
        if (entry.isIntersecting) {
          entry.target.classList.add('visible');
          observer.unobserve(entry.target);
        }
      });
    }, { threshold: 0.1 });

    this.featureCards.forEach(card => observer.observe(card.nativeElement));
  }

  @HostListener('document:mousemove', ['$event'])
  onMouseMove(e: MouseEvent) {
    if (this.bgVideo && this.bgVideo.nativeElement) {
      const moveX = (e.clientX - window.innerWidth / 2) * 0.015;
      const moveY = (e.clientY - window.innerHeight / 2) * 0.015;
      this.bgVideo.nativeElement.style.transform = `scale(1.1) translate(${moveX}px, ${moveY}px)`;
    }
  }
}
