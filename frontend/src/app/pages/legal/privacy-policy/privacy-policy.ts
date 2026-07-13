import { Component, OnInit, isDevMode, ChangeDetectorRef } from '@angular/core'; // 🚀 Importamos ChangeDetectorRef
import { CommonModule } from '@angular/common';
import { RouterModule } from '@angular/router';
import { TranslateModule, TranslateService } from '@ngx-translate/core';
import { HttpClient } from '@angular/common/http';
import { marked } from 'marked'; 

@Component({
  selector: 'app-privacy-policy',
  standalone: true,
  imports: [CommonModule, RouterModule, TranslateModule],
  templateUrl: './privacy-policy.html'
})
export class PrivacyPolicyComponent implements OnInit {
  currentLang: string = 'en';
  legalHTMLContent: string = ''; 
  lastUpdated: string = '';

  constructor(
    private translate: TranslateService, 
    private http: HttpClient,
    private cdr: ChangeDetectorRef // 🚀 Inyectamos la herramienta
  ) {
    this.currentLang = this.translate.currentLang || localStorage.getItem('bp_lang') || 'en';
  }

  ngOnInit() {
    this.loadLegalContent();
  }

  private getUrl() {
    const baseUrl = isDevMode() ? 'http://localhost:8000' : 'https://blackpenguin.ai';
    return `${baseUrl}/api/v1/system/legal/privacy?lang=${this.currentLang}`;
  }

  loadLegalContent() {
    this.legalHTMLContent = '<div class="flex justify-center items-center py-10"><span class="material-symbols-outlined animate-spin text-secondary text-4xl">sync</span></div>';

    this.http.get<any>(this.getUrl()).subscribe({
      next: async (data) => {
        try {
          this.lastUpdated = data?.last_updated_label || ''; 
          const rawMarkdown = data?.content_markdown || '*No content available.*';
          
          // 3. Convertimos el Markdown
          const parsed = await marked.parse(rawMarkdown);
          this.legalHTMLContent = parsed;
          
          // 🚀 LA MAGIA: Forzamos a Angular a mostrar el texto en pantalla de inmediato
          this.cdr.detectChanges(); 
          
        } catch (parseError) {
          this.legalHTMLContent = '<p class="text-red-400">Error rendering document layout.</p>';
          this.cdr.detectChanges(); // Forzar render de error
        }
      },
      error: (err) => {
        this.legalHTMLContent = '<p class="text-red-400">Error loading policy. Please try again later.</p>';
        this.cdr.detectChanges(); // Forzar render de error
      }
    });
  }

  switchLanguage(lang: string) {
    this.translate.use(lang);
    this.currentLang = lang;
    localStorage.setItem('bp_lang', lang);
    this.loadLegalContent(); 
  }
}