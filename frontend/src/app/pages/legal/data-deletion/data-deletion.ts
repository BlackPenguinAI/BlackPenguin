import { ChangeDetectorRef, Component, OnInit, isDevMode } from '@angular/core';
import { CommonModule } from '@angular/common';
import { HttpClient } from '@angular/common/http';
import { RouterModule } from '@angular/router';
import { marked } from 'marked';

@Component({
  selector: 'app-data-deletion',
  standalone: true,
  imports: [CommonModule, RouterModule],
  templateUrl: './data-deletion.html',
})
export class DataDeletionComponent implements OnInit {
  currentLang: 'en' | 'es' = 'en';
  legalHTMLContent = '';
  lastUpdated = '';

  constructor(private http: HttpClient, private cdr: ChangeDetectorRef) {}

  ngOnInit(): void { this.loadLegalContent(); }

  switchLanguage(lang: 'en' | 'es'): void {
    if (lang === this.currentLang) return;
    this.currentLang = lang;
    this.loadLegalContent();
  }

  private getUrl(): string {
    const baseUrl = isDevMode() ? 'http://localhost:8000' : 'https://blackpenguin.ai';
    return `${baseUrl}/api/v1/system/legal/data_deletion?lang=${this.currentLang}`;
  }

  private loadLegalContent(): void {
    this.legalHTMLContent = '<p class="text-gray-400">Loading deletion instructions…</p>';
    this.http.get<any>(this.getUrl()).subscribe({
      next: async data => {
        this.lastUpdated = data?.last_updated_label || '';
        this.legalHTMLContent = await marked.parse(data?.content_markdown || '*No content available.*');
        this.cdr.detectChanges();
      },
      error: () => {
        this.legalHTMLContent = '<p class="text-red-400">The deletion instructions could not be loaded. Contact info@blackpenguin.ai.</p>';
        this.cdr.detectChanges();
      },
    });
  }
}
