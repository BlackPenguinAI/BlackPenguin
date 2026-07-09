import { Component, ElementRef, ViewChild, ChangeDetectorRef, OnInit, isDevMode } from '@angular/core'; 
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterModule } from '@angular/router';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { TranslateModule, TranslateService } from '@ngx-translate/core';
import { ToastService } from '../../core/services/toast';

@Component({
  selector: 'app-chat',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterModule, TranslateModule],
  templateUrl: './chat.html',
  styleUrl: './chat.scss'
})
export class ChatComponent implements OnInit {
  @ViewChild('chatScroll') chatScroll!: ElementRef;

  prompt: string = '';
  isAnalyzing: boolean = false;
  currentLang: string = 'en';
  userName: string = '';

  selectedFile: File | null = null;
  isDragOver: boolean = false;
  
  // Mantenemos tu estructura original para no romper el HTML
  messages: { role: 'user' | 'ai', content: string, file?: string }[] = [];

  // Nuevo estado para saber si el onboarding ya finalizó
  isCompleted: boolean = false; 

  constructor(
    private translate: TranslateService,
    private http: HttpClient,         // 🚀 Usamos HttpClient directo para el onboarding
    private toastService: ToastService,
    private cdr: ChangeDetectorRef 
  ) {
    this.currentLang = this.translate.currentLang || localStorage.getItem('bp_lang') || 'en';
    this.userName = localStorage.getItem('bp_name') || 'Admin';
  }

  // ==========================================
  // 🚀 RUTAS DEL BACKEND DE ONBOARDING
  // ==========================================
  private get sessionUrl() {
    return isDevMode() 
      ? 'http://localhost:8000/api/v1/tenants/onboarding/session' 
      : 'https://blackpenguin.ai/api/v1/tenants/onboarding/session';
  }

  private get chatUrl() {
    return isDevMode() 
      ? 'http://localhost:8000/api/v1/tenants/onboarding/chat' 
      : 'https://blackpenguin.ai/api/v1/tenants/onboarding/chat';
  }

  private get headers() {
    const token = localStorage.getItem('bp_token');
    return new HttpHeaders().set('Authorization', `Bearer ${token}`);
  }

  ngOnInit() {
    this.loadSession();
  }

  // ==========================================
  // 🧠 LÓGICA CORE: CARGA Y ENVÍO DE MENSAJES
  // ==========================================
  loadSession() {
    this.isAnalyzing = true;
    this.http.get<any>(this.sessionUrl, { headers: this.headers }).subscribe({
      next: (data) => {
        this.isCompleted = data.is_completed;
        
        // Mapeamos los mensajes de la BD al formato que usa tu HTML
        this.messages = (data.messages || []).map((m: any) => ({
          role: m.sender === 'user' ? 'user' : 'ai',
          content: m.content
        }));
        
        this.isAnalyzing = false;
        this.scrollToBottom();
        this.cdr.detectChanges();
      },
      error: (err) => {
        this.isAnalyzing = false;
        this.toastService.showError(err.error?.detail || 'Error al cargar la sesión de onboarding.');
        this.cdr.detectChanges();
      }
    });
  }

  sendMessage() {
    if (!this.prompt.trim() || this.isAnalyzing || this.isCompleted) return;

    // Validación temporal: En Onboarding no usamos PDFs por ahora
    if (this.selectedFile) {
       this.toastService.showError('El envío de archivos no está habilitado en esta fase de Onboarding.');
       return;
    }

    const userText = this.prompt.trim();
    
    // 1. Agregar el mensaje visualmente de inmediato
    this.messages.push({ role: 'user', content: userText });
    this.prompt = '';
    this.isAnalyzing = true;
    this.scrollToBottom();
    this.cdr.detectChanges();

    // 2. Enviar el mensaje al motor de IA en el backend
    this.http.post<any>(this.chatUrl, { message: userText }, { headers: this.headers }).subscribe({
      next: (aiMsg) => {
        this.isAnalyzing = false;
        // La IA nos responde y lo agregamos a la pantalla
        this.messages.push({ role: 'ai', content: aiMsg.content });
        this.scrollToBottom();
        this.cdr.detectChanges(); 
      },
      error: (err) => {
        this.isAnalyzing = false;
        this.toastService.showError(err.error?.detail || 'Error en la comunicación con la IA.');
        this.messages.push({ role: 'ai', content: '❌ Hubo un problema de conexión. Intenta de nuevo.' });
        this.scrollToBottom();
        this.cdr.detectChanges();
      }
    });
  }

  // ==========================================
  // 🔗 MÉTODOS PUENTE PARA LA VISTA (HTML)
  // ==========================================

  setPrompt(textKey: string) {
    // Toma la llave de traducción de las sugerencias y la pone en el input
    this.prompt = this.translate.instant(textKey);
  }

  startAnalysis(event?: any) {
    // Si el usuario presionó la tecla "Enter", evitamos que haga un salto de línea
    if (event) {
      event.preventDefault();
    }
    // Llamamos a la lógica maestra del chat que construimos antes
    this.sendMessage();
  }

  scrollToBottom() {
    setTimeout(() => {
      if (this.chatScroll) {
        this.chatScroll.nativeElement.scrollTop = this.chatScroll.nativeElement.scrollHeight;
      }
    }, 100);
  }

  // ==========================================
  // 📎 MÉTODOS DE IDIOMAS Y ARCHIVOS (UI Original)
  // ==========================================
  switchLanguage(lang: string) {
    this.translate.use(lang);
    this.currentLang = lang;
    localStorage.setItem('bp_lang', lang);
  }

  onDragOver(event: DragEvent) {
    event.preventDefault();
    this.isDragOver = true;
  }

  onDragLeave(event: DragEvent) {
    event.preventDefault();
    this.isDragOver = false;
  }

  onDrop(event: DragEvent) {
    event.preventDefault();
    this.isDragOver = false;
    if (event.dataTransfer && event.dataTransfer.files.length > 0) {
      this.selectedFile = event.dataTransfer.files[0];
    }
  }

  onFileSelected(event: any) {
    if (event.target.files.length > 0) {
      this.selectedFile = event.target.files[0];
    }
  }

  removeFile() {
    this.selectedFile = null;
  }
}