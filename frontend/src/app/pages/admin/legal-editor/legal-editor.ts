import { Component, OnInit, isDevMode } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { ToastService } from '../../../core/services/toast';

@Component({
  selector: 'app-legal-editor',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './legal-editor.html'
})
export class LegalEditorComponent implements OnInit {
  activeDoc: 'privacy' | 'terms' = 'privacy';
  activeLang: 'en' | 'es' = 'en';

  isLoading: boolean = false;
  isSaving: boolean = false;

  documentData = {
    last_updated_label: '',
    content_markdown: ''
  };

  constructor(private http: HttpClient, private toast: ToastService) {}

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
    this.activeDoc = type;
    this.loadDocument();
  }

  setLang(lang: 'en' | 'es') {
    this.activeLang = lang;
    this.loadDocument();
  }

  loadDocument() {
    this.isLoading = true;
    const url = `${this.baseUrl}/api/v1/system/legal/${this.activeDoc}?lang=${this.activeLang}`;
    
    // Al cargar, no mandamos headers porque recuerda que el endpoint GET es público
    this.http.get<any>(url).subscribe({
      next: (data) => {
        this.documentData.last_updated_label = data.last_updated_label || '';
        this.documentData.content_markdown = data.content_markdown || '';
        this.isLoading = false;
      },
      error: () => {
        this.toast.showError('Error al cargar el documento.');
        this.isLoading = false;
      }
    });
  }

  saveDocument() {
    this.isSaving = true;
    const url = `${this.baseUrl}/api/v1/system/legal/${this.activeDoc}?lang=${this.activeLang}`;
    
    // Al guardar SÍ mandamos el Token del Superadmin
    this.http.put<any>(url, this.documentData, { headers: this.headers }).subscribe({
      next: () => {
        this.toast.showSuccess('Documento actualizado en la base de datos.');
        this.isSaving = false;
      },
      error: () => {
        this.toast.showError('Error al guardar. Verifica tu conexión.');
        this.isSaving = false;
      }
    });
  }
}