import { Component, ElementRef, ViewChild, OnInit, isDevMode } from '@angular/core'; 
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

  // Interfaz Multimodal
  selectedFile: File | null = null;
  isDragOver: boolean = false;
  isRecording: boolean = false; // Estado para la futura capa de voz

  // Estados Cognitivos
  messages: any[] = [];
  profile: any = {};
  isCompleted: boolean = false;

  constructor(
    private translate: TranslateService,
    private http: HttpClient
  ) {
    this.currentLang = this.translate.currentLang || localStorage.getItem('bp_lang') || 'en';
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
    this.userName = localStorage.getItem('bp_name') || 'Executive';
    this.loadSession();
    this.loadProfile();
  }

  loadSession() {
    this.http.get<any>(`${this.baseUrl}/session`, { headers: this.headers }).subscribe({
      next: (data) => {
        this.messages = data.messages || [];
        this.isCompleted = data.is_completed;
        this.scrollToBottom();
      },
      error: (err) => console.error('Error loading session', err)
    });
  }

  loadProfile() {
    this.http.get<any>(`${this.baseUrl}/profile`, { headers: this.headers }).subscribe({
      next: (data) => {
        this.profile = data;
      },
      error: (err) => console.error('Error loading profile', err)
    });
  }

  startAnalysis(event?: any) {
    if (event) {
      event.preventDefault(); // Prevenir salto de línea con Enter
    }
    this.sendMessage();
  }

  sendMessage() {
    if (!this.prompt.trim() && !this.selectedFile) return;

    // 1. Ensamblar mensaje con adjunto (MVP)
    let finalMessage = this.prompt;
    if (this.selectedFile) {
      finalMessage = `[Documento adjunto: ${this.selectedFile.name}]\n` + finalMessage;
    }

    // 2. Reflejar instantáneamente en la interfaz
    this.messages.push({
      sender: 'user',
      content: finalMessage,
      created_at: new Date().toISOString()
    });

    const payload = { message: finalMessage };
    
    // Limpiar input
    this.prompt = '';
    this.selectedFile = null;
    this.isAnalyzing = true;
    this.scrollToBottom();

    // 3. Enviar al Backend (Deepseek IA)
    this.http.post<any>(`${this.baseUrl}/chat`, payload, { headers: this.headers }).subscribe({
      next: (aiResponse) => {
        this.messages.push(aiResponse);
        this.isAnalyzing = false;
        this.scrollToBottom();
        
        // 🚀 WOW EFFECT: Refrescar el Tracker para ver si la IA descubrió nuevos datos
        this.loadProfile();
      },
      error: (err) => {
        console.error('Error sending message', err);
        this.isAnalyzing = false;
      }
    });
  }

  // ==========================================
  // 📎 MÉTODOS MULTIMODALES (Archivos y Voz)
  // ==========================================
  onFileSelected(event: any) {
    if (event.target.files && event.target.files.length > 0) {
      this.selectedFile = event.target.files[0];
    }
  }

  removeFile() {
    this.selectedFile = null;
  }

  toggleRecording() {
    this.isRecording = !this.isRecording;
    if (this.isRecording) {
      this.prompt = "🎙️ Escuchando... (Hable ahora)";
    } else {
      this.prompt = "";
    }
  }

  scrollToBottom() {
    setTimeout(() => {
      if (this.chatScroll) {
        this.chatScroll.nativeElement.scrollTop = this.chatScroll.nativeElement.scrollHeight;
      }
    }, 100);
  }

  switchLanguage(lang: string) {
    this.translate.use(lang);
    this.currentLang = lang;
    localStorage.setItem('bp_lang', lang);
  }
}