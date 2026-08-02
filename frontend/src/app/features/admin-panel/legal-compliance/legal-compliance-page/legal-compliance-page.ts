import { Component, OnInit, ChangeDetectorRef, isDevMode } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { ToastService } from '../../../../core/services/toast';

import { GlassCardComponent } from '../../../../shared/ui/glass-card/glass-card';
import { InputComponent } from '../../../../shared/ui/input/input';
import { ButtonComponent } from '../../../../shared/ui/button/button';

@Component({
  selector: 'app-legal-compliance-page',
  standalone: true,
  imports: [CommonModule, FormsModule, GlassCardComponent, InputComponent, ButtonComponent],
  templateUrl: './legal-compliance-page.html'
})
export class LegalCompliancePageComponent implements OnInit {
  
  currentDocType: 'privacy' | 'terms' = 'privacy';
  currentLang: 'en' | 'es' = 'en';

  legalDoc = {
    content_markdown: '',
    last_updated_label: ''
  };

  isLoading: boolean = false;
  isSaving: boolean = false;

  constructor(
    private http: HttpClient,
    private toast: ToastService,
    private cdr: ChangeDetectorRef
  ) {}

  ngOnInit() {
    this.loadDocument();
  }

  private get baseUrl() {
    return isDevMode() ? 'http://localhost:8000' : 'https://blackpenguin.ai';
  }

  private get headers() {
    const token = localStorage.getItem('bp_token');
    return new HttpHeaders().set('Authorization', `Bearer ${token}`);
  }

  setDocType(type: 'privacy' | 'terms') {
    if (this.currentDocType === type) return;
    this.currentDocType = type;
    this.loadDocument();
  }

  setLang(lang: 'en' | 'es') {
    if (this.currentLang === lang) return;
    this.currentLang = lang;
    this.loadDocument();
  }

  loadDocument() {
    this.isLoading = true;
    this.cdr.detectChanges();

    this.http.get<any>(`${this.baseUrl}/api/v1/system/legal/${this.currentDocType}?lang=${this.currentLang}`, { headers: this.headers }).subscribe({
      next: (data) => {
        this.legalDoc = {
          content_markdown: data.content_markdown || '',
          last_updated_label: data.last_updated_label || ''
        };
        this.isLoading = false;
        this.cdr.detectChanges();
      },
      error: () => {
        this.toast.showError('Failed to load legal document.');
        this.isLoading = false;
        this.cdr.detectChanges();
      }
    });
  }

  saveDocument() {
    if (!this.legalDoc.last_updated_label || !this.legalDoc.content_markdown) {
      this.toast.showError('All fields are required.');
      return;
    }

    this.isSaving = true;
    this.cdr.detectChanges();

    this.http.put<any>(`${this.baseUrl}/api/v1/system/legal/${this.currentDocType}?lang=${this.currentLang}`, this.legalDoc, { headers: this.headers }).subscribe({
      next: () => {
        this.toast.showSuccess('Document saved successfully.');
        this.isSaving = false;
        this.cdr.detectChanges();
      },
      error: (err) => {
        this.toast.showError(err.error?.detail || 'Failed to save document.');
        this.isSaving = false;
        this.cdr.detectChanges();
      }
    });
  }
}