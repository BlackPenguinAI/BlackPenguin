import { Component, AfterViewInit, OnDestroy, ViewChild, ElementRef, ViewChildren, QueryList, isDevMode, ChangeDetectorRef } from '@angular/core';
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
export class LandingComponent implements AfterViewInit, OnDestroy {
  readonly backgroundVideoSrc = 'https://d8j0ntlcm91z4.cloudfront.net/user_38xzZboKViGWJOttwIXH07lWA1P/hf_20260403_050628_c4e32401-fab4-4a27-b7a8-6e9291cd5959.mp4';

  email: string = '';
  isSubmitting: boolean = false;
  showSuccess: boolean = false;
  errorMessage: string = ''; 
  currentLang: string = 'en';
  isMobileMenuOpen: boolean = false;
  heroSubtitle: string = '';
  private backgroundSegmentStart = 0;
  private backgroundSegmentEnd = 0;
  private backgroundTimeCheck?: number;

  @ViewChild('bgVideo') bgVideo!: ElementRef<HTMLVideoElement>;
  @ViewChild('heroHeading') heroHeading!: ElementRef<HTMLHeadingElement>;
  @ViewChild('heroSubheading') heroSubheading!: ElementRef<HTMLParagraphElement>;
  @ViewChild('heroCta') heroCta!: ElementRef<HTMLDivElement>;
  @ViewChildren('featureCard') featureCards!: QueryList<ElementRef<HTMLDivElement>>;

  constructor(
    private translate: TranslateService,
    private http: HttpClient,
    private cdr: ChangeDetectorRef // 🚀 NUEVO: Inyectamos el actualizador de vista
  ) {
    this.currentLang = 'en';
    this.translate.use(this.currentLang).subscribe(() => this.refreshHeroSubtitle());
    localStorage.setItem('bp_lang', this.currentLang);
  }

  switchLanguage(lang: string) {
    this.currentLang = lang;
    localStorage.setItem('bp_lang', lang);
    this.translate.use(lang).subscribe(() => {
      this.refreshHeroSubtitle();
      this.cdr.detectChanges();
    });
  }

  get heroSubtitleWords(): string[] {
    return this.heroSubtitle.split(' ').filter(Boolean);
  }

  getRollDelay(index: number, total: number): string {
    const midpoint = (total - 1) / 2;
    return `${Math.abs(index - midpoint) * 35}ms`;
  }

  isInverseHeroWord(word: string): boolean {
    return ['revenue', 'opportunities'].includes(word.toLowerCase());
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
      this.syncBackgroundVideoSegment();
      this.bgVideo.nativeElement.play().catch(() => {});
    }
    this.backgroundTimeCheck = window.setInterval(() => this.syncBackgroundVideoSegment(), 60_000);
    this.triggerFadeIns();
    this.setupScrollObserver();
  }

  ngOnDestroy() {
    if (this.backgroundTimeCheck) {
      window.clearInterval(this.backgroundTimeCheck);
    }
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
    setTimeout(() => this.heroSubheading.nativeElement.classList.add('visible'), 1000);
    setTimeout(() => this.heroCta.nativeElement.classList.add('visible'), 1300);
  }

  private refreshHeroSubtitle() {
    const subtitle = this.translate.instant('HERO.SUBTITLE');
    this.heroSubtitle = subtitle === 'HERO.SUBTITLE' ? '' : subtitle;
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

  syncBackgroundVideoSegment() {
    const video = this.bgVideo?.nativeElement;
    if (!video || !Number.isFinite(video.duration) || video.duration <= 0) {
      return;
    }

    const segmentBoundary = video.duration / 2;
    const segmentPadding = Math.max(1, segmentBoundary * 0.08);
    const isClearSkyTime = this.isClearSkyTime(new Date());
    const nextStart = isClearSkyTime ? segmentPadding : segmentBoundary + segmentPadding;
    const nextEnd = isClearSkyTime ? segmentBoundary : video.duration;
    const segmentChanged = nextStart !== this.backgroundSegmentStart || nextEnd !== this.backgroundSegmentEnd;

    this.backgroundSegmentStart = nextStart;
    this.backgroundSegmentEnd = nextEnd;

    if (segmentChanged || video.currentTime < nextStart || video.currentTime >= nextEnd) {
      video.currentTime = nextStart;
      video.play().catch(() => {});
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
