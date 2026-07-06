import { Component, AfterViewInit, ViewChild, ElementRef, ViewChildren, QueryList, HostListener, isDevMode } from '@angular/core'; // 🚀 Agregamos isDevMode al final
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterModule } from '@angular/router'; // 🚀 ¡CRÍTICO: Importación agregada para habilitar routerLink!
import { TranslateModule, TranslateService } from '@ngx-translate/core';
import { HttpClient } from '@angular/common/http'; // 🚀 IMPORTANTE: Añadir HttpClient

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
  errorMessage: string = ''; // 🚀 Variable para errores
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
    private http: HttpClient // 🚀 Inyectamos el cliente HTTP
  ) {
    this.currentLang = localStorage.getItem('bp_lang') || 'en';
    this.translate.onLangChange.subscribe((event) => {
      this.currentLang = event.lang;
    });
  }

  switchLanguage(lang: string) {
    this.translate.use(lang);
    localStorage.setItem('bp_lang', lang);
  }

  toggleMobileMenu() {
    this.isMobileMenuOpen = !this.isMobileMenuOpen;
  }

  scrollToSection(sectionId: string) {
    const element = document.getElementById(sectionId);
    if (element) {
      const elementPosition = element.getBoundingClientRect().top + window.scrollY;
      const offsetPosition = elementPosition - 120;

      window.scrollTo({
        top: offsetPosition,
        behavior: 'smooth'
      });
    }
  }

  joinWaitlist() {
    if (!this.email) return;

    this.isSubmitting = true;
    this.showSuccess = false;

    setTimeout(() => {
      this.isSubmitting = false;
      this.showSuccess = true;
      this.email = '';

      setTimeout(() => this.showSuccess = false, 5000);
    }, 1500);
  }

  ngAfterViewInit() {
    this.animateHeroText();
    this.triggerFadeIns();
    this.setupScrollObserver();

    if (this.bgVideo && this.bgVideo.nativeElement) {
      this.bgVideo.nativeElement.muted = true;
      this.bgVideo.nativeElement.play().catch(err => console.log('Autoplay bloqueado temporalmente:', err));
    }
  }

  private animateHeroText() {
    if (!this.heroHeading) return;
    this.heroHeading.nativeElement.innerHTML = ''; 

    this.translate.get('HERO.TITLE').subscribe((translatedText: string) => {
      const initialDelay = 150;
      const stagger = 35;
      const words = translatedText.split(/(\s+)/);
      let charIndex = 0;
      
      words.forEach(word => {
        if (word === '\n') {
          this.heroHeading.nativeElement.appendChild(document.createElement('br'));
        } else if (word.trim() === '') {
          this.heroHeading.nativeElement.appendChild(document.createTextNode(' '));
        } else {
          const wordSpan = document.createElement('span');
          wordSpan.className = 'whitespace-nowrap';
          
          word.split('').forEach(char => {
            const charSpan = document.createElement('span');
            charSpan.textContent = char;
            charSpan.className = 'char-animate';
            wordSpan.appendChild(charSpan);
            
            setTimeout(() => {
              charSpan.classList.add('visible');
            }, initialDelay + (charIndex * stagger));
            charIndex++;
          });
          this.heroHeading.nativeElement.appendChild(wordSpan);
        }
      });
    });
  }

  // 🚀 LÓGICA DE ENVÍO DE MAILCHIMP A TRAVÉS DE FASTAPI
  onSubmit() {
    if (!this.email || this.isSubmitting) return;
    
    this.isSubmitting = true;
    this.errorMessage = '';

    const apiUrl = isDevMode() 
      ? 'http://localhost:8000/api/v1/leads/waitlist' 
      : 'https://blackpenguin.ai/api/v1/leads/waitlist';

    this.http.post(apiUrl, { email: this.email }).subscribe({
      next: (res: any) => {
        this.isSubmitting = false;
        this.showSuccess = true;
        this.email = ''; // Limpiar el input
        
        // El éxito desaparece después de 5 segundos
        setTimeout(() => this.showSuccess = false, 5000);
      },
      error: (err) => {
        this.isSubmitting = false;
        this.errorMessage = err.error?.detail || 'Ocurrió un error. Intenta de nuevo.';
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