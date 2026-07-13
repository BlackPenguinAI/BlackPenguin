import { Component, ElementRef, ViewChild, OnInit, isDevMode, ChangeDetectorRef } from '@angular/core'; 
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterModule } from '@angular/router';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { TranslateModule, TranslateService } from '@ngx-translate/core';

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
  isRecording: boolean = false; 

  messages: any[] = [];
  profile: any = {};
  isCompleted: boolean = false;

  constructor(
    private translate: TranslateService,
    private http: HttpClient,
    private cdr: ChangeDetectorRef // 🚀 Control nativo de renderizado inyectado
  ) {
    // 🚀 FORZAR INGLÉS POR DEFECTO (Si no hay idioma, siempre será 'en')
    this.currentLang = localStorage.getItem('bp_lang') || 'en';
    this.translate.use(this.currentLang);
    localStorage.setItem('bp_lang', this.currentLang); // Lo fijamos
  }

  private get baseUrl() {
    return isDevMode() 
      ? 'http://localhost:8000/api/v1/tenants/onboarding' 
      : 'https://blackpenguin.ai/api/v1/tenants/onboarding';
  }

  private get headers() {
    const token = localStorage.getItem('bp_token');
    return new HttpHeaders().set('Authorization', `Bearer ${token}`);
  }

  ngOnInit() {
    this.userName = localStorage.getItem('bp_name') || 'User';
    this.loadProfile();
    this.loadChatHistory();
  }

  loadProfile() {
    this.http.get<any>(`${this.baseUrl}/profile`, { headers: this.headers }).subscribe({
      next: (data) => {
        this.profile = data;
        // 🚀 OBLIGAMOS AL TRACKER LATERAL A PINTAR LOS CHECKMARKS AL INSTANTE
        this.cdr.detectChanges(); 
      },
      error: (err) => {
        console.error('Error loading profile', err);
        this.cdr.detectChanges();
      }
    });
  }

  loadChatHistory() {
    this.http.get<any[]>(`${this.baseUrl}/chat`, { headers: this.headers }).subscribe({
      next: (data) => {
        this.messages = data;
        this.scrollToBottom();
        this.cdr.detectChanges();
      },
      error: (err) => {
        console.error('Error loading history', err);
        this.cdr.detectChanges();
      }
    });
  }

  sendMessage() {
    if (!this.prompt.trim() && !this.selectedFile) return;

    const userText = this.prompt;
    this.prompt = '';
    
    // 1. Mostrar mensaje del usuario en la UI instantáneamente
    this.messages.push({ sender: 'user', content: userText, created_at: new Date() });
    this.isAnalyzing = true;
    this.scrollToBottom();
    this.cdr.detectChanges(); // 🚀 Forzar repintado del chat

    const payload = { message: userText };

    // 2. Enviar al Backend (Deepseek IA)
    this.http.post<any>(`${this.baseUrl}/chat`, payload, { headers: this.headers }).subscribe({
      next: (aiResponse) => {
        this.messages.push(aiResponse);
        this.isAnalyzing = false;
        this.scrollToBottom();
        
        // 🚀 WOW EFFECT: Recargamos el perfil para que el Tracker Lateral (Derecho) 
        // marque las palomitas verdes si la IA acaba de extraer nueva información
        this.loadProfile(); 
      },
      error: (err) => {
        console.error('Error sending message', err);
        this.isAnalyzing = false;
        this.cdr.detectChanges();
      }
    });
  }

  onFileSelected(event: any) {
    if (event.target.files && event.target.files.length > 0) {
      this.selectedFile = event.target.files[0];
      this.cdr.detectChanges();
    }
  }

  removeFile() {
    this.selectedFile = null;
    this.cdr.detectChanges();
  }

  toggleRecording() {
    this.isRecording = !this.isRecording;
    this.prompt = this.isRecording ? "🎙️ Escuchando... (Hable ahora)" : "";
    this.cdr.detectChanges();
  }

  scrollToBottom() {
    setTimeout(() => {
      if (this.chatScroll) {
        this.chatScroll.nativeElement.scrollTop = this.chatScroll.nativeElement.scrollHeight;
      }
    }, 100);
  }
}