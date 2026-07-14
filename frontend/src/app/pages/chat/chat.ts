import { Component, ElementRef, ViewChild, OnInit, OnDestroy, isDevMode, ChangeDetectorRef } from '@angular/core'; 
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterModule } from '@angular/router';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { TranslateModule, TranslateService } from '@ngx-translate/core';
import { interval, Subscription } from 'rxjs'; // 🚀 IMPORTACIONES NUEVAS

@Component({
  selector: 'app-chat',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterModule, TranslateModule],
  templateUrl: './chat.html',
  styleUrl: './chat.scss'
})
export class ChatComponent implements OnInit, OnDestroy {
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

  private profilePollSub?: Subscription; // 🚀 CONTROLADOR DEL POLLING

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
    this.initSession(); 
    this.startProfilePolling(); // 🚀 INICIAR MAGIA EN TIEMPO REAL
  }

  ngOnDestroy() {
    // 🚀 Limpiar el polling al salir de la pantalla para evitar fugas de memoria
    if (this.profilePollSub) this.profilePollSub.unsubscribe();
  }

  startProfilePolling() {
    // Consultar silenciosamente la BD cada 4 segundos si el perfil no está al 100%
    this.profilePollSub = interval(4000).subscribe(() => {
      if (!this.profile.is_profile_fully_completed) {
        this.loadProfile();
      }
    });
  }

  initSession() {
    this.http.get<any>(`${this.baseUrl}/session`, { headers: this.headers }).subscribe({
      next: (sessionData) => {
        this.isCompleted = sessionData.is_completed;
        this.loadChatHistory();
      }
    });
  }

  loadProfile() {
    this.http.get<any>(`${this.baseUrl}/profile`, { headers: this.headers }).subscribe({
      next: (data) => {
        this.profile = data;
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
    const fileToUpload = this.selectedFile; // 🚀 Capturamos el archivo
    
    this.prompt = ''; 
    this.selectedFile = null; // 🚀 Desaparece del input visualmente
    
    // 1. Mostrar en UI el texto y el archivo asociado a esta burbuja
    this.messages.push({ 
      sender: 'user', 
      content: userText, 
      file_name: fileToUpload ? fileToUpload.name : null, // 🚀 Adjuntamos el nombre
      created_at: new Date() 
    });
    
    this.isAnalyzing = true;
    this.scrollToBottom();
    this.cdr.detectChanges(); 

    // 2. 🚀 Usar FormData en lugar de JSON para enviar el archivo físico
    const formData = new FormData();
    formData.append('message', userText);
    if (fileToUpload) {
      formData.append('file', fileToUpload);
    }

    this.http.post<any>(`${this.baseUrl}/chat`, formData, { headers: this.headers }).subscribe({
      next: (aiResponse) => {
        this.messages.push(aiResponse);
        this.isAnalyzing = false;
        this.scrollToBottom();
        this.loadProfile(); // Refresco inmediato
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