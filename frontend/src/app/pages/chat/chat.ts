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
    private cdr: ChangeDetectorRef
  ) {
    this.currentLang = localStorage.getItem('bp_lang') || 'en';
    this.translate.use(this.currentLang);
    localStorage.setItem('bp_lang', this.currentLang); 
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
    this.initSession(); // 🚀 Primero inicializamos la sesión en BD
  }

  // 🚀 NUEVA FUNCIÓN: Llama al endpoint que crea la sala de chat en PostgreSQL
  initSession() {
    this.http.get<any>(`${this.baseUrl}/session`, { headers: this.headers }).subscribe({
      next: (sessionData) => {
        this.isCompleted = sessionData.is_completed;
        // Una vez que la sesión fue creada, cargamos los mensajes (incluirá el Welcome Message)
        this.loadChatHistory();
      },
      error: (err) => {
        console.error('Error inicializando la sesión', err);
        this.cdr.detectChanges();
      }
    });
  }

  loadProfile() {
    this.http.get<any>(`${this.baseUrl}/profile`, { headers: this.headers }).subscribe({
      next: (data) => {
        this.profile = data;
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

  get canSend(): boolean {
    const hasText = this.prompt && this.prompt.trim().length > 0;
    const hasFile = this.selectedFile !== null;
    return (hasText || hasFile) && !this.isAnalyzing && !this.isRecording && !this.isCompleted;
  }

  handleKeyDown(event: KeyboardEvent) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault(); 
      if (this.canSend) {
        this.sendMessage();
      }
    }
  }

  sendMessage() {
    if (!this.canSend) return;

    const userText = this.prompt.trim();
    this.prompt = ''; 
    
    this.messages.push({ sender: 'user', content: userText, created_at: new Date() });
    this.isAnalyzing = true;
    this.scrollToBottom();
    this.cdr.detectChanges(); 

    const payload = { message: userText };

    this.http.post<any>(`${this.baseUrl}/chat`, payload, { headers: this.headers }).subscribe({
      next: (aiResponse) => {
        this.messages.push(aiResponse);
        this.isAnalyzing = false;
        this.scrollToBottom();
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