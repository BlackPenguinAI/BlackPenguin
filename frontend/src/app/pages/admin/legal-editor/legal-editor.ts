import { Component, OnInit, isDevMode, ChangeDetectorRef } from '@angular/core'; // 🚀 Importado ChangeDetectorRef
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

  constructor(
    private http: HttpClient, 
    private toast: ToastService,
    private cdr: ChangeDetectorRef // 🚀 Inyectamos el control de renderizado
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
    this.activeDoc = type;
    this.loadDocument();
    this.cdr.detectChanges(); // 🚀 Forzamos cambio visual inmediato en las pestañas de documento
  }

  setLang(lang: 'en' | 'es') {
    this.activeLang = lang;
    this.loadDocument();
    this.cdr.detectChanges(); // 🚀 Forzamos cambio visual inmediato en las pestañas de idioma
  }

  loadDocument() {
    this.isLoading = true;
    this.cdr.detectChanges(); // 🚀 Muestra el backdrop con el spinner asíncrono
    
    const url = `${this.baseUrl}/api/v1/system/legal/${this.activeDoc}?lang=${this.activeLang}`;
    
    this.http.get<any>(url).subscribe({
      next: (data) => {
        this.documentData.last_updated_label = data.last_updated_label || '';
        this.documentData.content_markdown = data.content_markdown || '';
        this.isLoading = false;
        this.cdr.detectChanges(); // 🚀 Rellena los textareas y apaga el spinner en el DOM
      },
      error: () => {
        this.toast.showError('Error al cargar el documento.');
        this.isLoading = false;
        this.cdr.detectChanges(); // 🚀 Apaga el spinner si ocurre un error de conexión
      }
    });
  }

  saveDocument() {
    this.isSaving = true;
    this.cdr.detectChanges(); // 🚀 Deshabilita el botón e inyecta el loader de guardado
    
    const url = `${this.baseUrl}/api/v1/system/legal/${this.activeDoc}?lang=${this.activeLang}`;
    
    this.http.put<any>(url, this.documentData, { headers: this.headers }).subscribe({
      next: () => {
        this.toast.showSuccess('Documento actualizado en la base de datos.');
        this.isSaving = false;
        this.cdr.detectChanges(); // 🚀 Restaura el estado normal del botón al guardar con éxito
      },
      error: () => {
        this.toast.showError('Error al guardar. Verifica tu conexión.');
        this.isSaving = false;
        this.cdr.detectChanges(); // 🚀 Restaura el estado del botón si la API da error
      }
    });
  }
}