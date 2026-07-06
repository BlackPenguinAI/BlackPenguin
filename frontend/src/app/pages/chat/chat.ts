import { Component, ElementRef, ViewChild, ChangeDetectorRef } from '@angular/core'; // 🚀 Agregado ChangeDetectorRef
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterModule } from '@angular/router';
import { TranslateModule, TranslateService } from '@ngx-translate/core';
import { ChatService } from '../../core/services/chat';
import { ToastService } from '../../core/services/toast';

@Component({
  selector: 'app-chat',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterModule, TranslateModule],
  templateUrl: './chat.html',
  styleUrl: './chat.scss'
})
export class ChatComponent {
  @ViewChild('chatScroll') chatScroll!: ElementRef;

  prompt: string = '';
  isAnalyzing: boolean = false;
  isSidebarOpen: boolean = false;
  currentLang: string = 'en';
  userName: string = '';

  selectedFile: File | null = null;
  isDragOver: boolean = false;
  messages: { role: 'user' | 'ai', content: string, file?: string }[] = [];

  sessionId: string = ''; // 🚀 Asegúrate de tener esta variable creada

  constructor(
    private translate: TranslateService,
    private chatService: ChatService,
    private toastService: ToastService,
    private cdr: ChangeDetectorRef // 🚀 Inyectamos el detector de cambios
  ) {
    this.currentLang = this.translate.currentLang || localStorage.getItem('bp_lang') || 'en';
    this.userName = localStorage.getItem('bp_name') || 'Admin';
  }

  // --- MÉTODOS DE IDIOMAS Y SIDEBAR ---
  switchLanguage(lang: string) {
    this.translate.use(lang);
    this.currentLang = lang;
    localStorage.setItem('bp_lang', lang);
  }

  toggleSidebar() {
    this.isSidebarOpen = !this.isSidebarOpen;
  }

  setPrompt(translateKey: string) {
    this.translate.get(translateKey).subscribe((text: string) => {
      this.prompt = text;
      this.startAnalysis();
    });
  }

  // --- MÉTODOS DE DRAG & DROP ---
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
    const files = event.dataTransfer?.files;
    this.handleFiles(files);
  }

  onFileSelected(event: any) {
    this.handleFiles(event.target.files);
  }

  private handleFiles(files: FileList | null | undefined) {
    if (files && files.length > 0) {
      if (files[0].type === 'application/pdf') {
        this.selectedFile = files[0];
        this.toastService.showSuccess(`PDF Listo para analizar: ${this.selectedFile.name}`);
        this.cdr.detectChanges(); // Forzamos actualización para mostrar el archivo
      } else {
        this.toastService.showError('Solo se permiten archivos en formato PDF.');
      }
    }
  }

  removeFile() {
    this.selectedFile = null;
  }

  // --- LÓGICA MAESTRA DEL CHAT REACTIVO ---
  startAnalysis(event?: Event) {
    if (event) {
      const keyboardEvent = event as KeyboardEvent;
      if (keyboardEvent.key === 'Enter' && !keyboardEvent.shiftKey) {
        keyboardEvent.preventDefault();
      } else {
        return;
      }
    }

    if ((!this.prompt.trim() && !this.selectedFile) || this.isAnalyzing) return;

    // Si no hay prompt pero sí archivo, ponemos un texto por defecto invisible
    const userMessage = this.prompt.trim() || 'Por favor procesa los datos y dime qué encontraste.';
    
    // Mostramos el mensaje del usuario de inmediato
    this.messages.push({ role: 'user', content: userMessage, file: this.selectedFile?.name });
    
    const currentPrompt = this.prompt;
    this.prompt = '';
    this.isAnalyzing = true;
    this.scrollToBottom();
    
    // 🚀 OBLIGAMOS A ANGULAR A RENDERIZAR LA BURBUJA Y EL LOADING DE INMEDIATO
    this.cdr.detectChanges(); 

    if (this.selectedFile) {
       // 1. MODO EXTRACCIÓN (Usuario sube el PDF inicial)
       //this.chatService.analyzeDocument(this.selectedFile, currentPrompt).subscribe({
       this.chatService.analyzeDocument(this.sessionId, this.selectedFile, currentPrompt).subscribe({
         next: (res) => {
           this.isAnalyzing = false;
           this.messages.push({ role: 'ai', content: res.message });
           this.selectedFile = null; 
           this.scrollToBottom();
           this.cdr.detectChanges(); // 🚀 Aparece la respuesta sola sin hacer clic
         },
         error: (err) => {
           this.isAnalyzing = false;
           this.toastService.showError('Error al analizar el PDF con la IA.');
           this.messages.push({ role: 'ai', content: '❌ Ocurrió un error conectando con el servidor. Intenta de nuevo.' });
           this.scrollToBottom();
           this.cdr.detectChanges();
         }
       });
    } else {
       // 2. MODO CONVERSACIÓN (Usuario responde tras recibir los datos)
       // 🚀 CORRECCIÓN: Traducimos 'ai' a 'assistant' para que OpenAI lo entienda
       const history = this.messages.map(m => ({ 
         role: m.role === 'ai' ? 'assistant' : m.role, 
         content: m.content 
       }));
       
       this.chatService.sendMessage(this.sessionId, history).subscribe({
         next: (res) => {
           this.isAnalyzing = false;
           this.messages.push({ role: 'ai', content: res.message });
           this.scrollToBottom();
           this.cdr.detectChanges(); // 🚀 Respuesta en tiempo real
         },
         error: (err) => {
           this.isAnalyzing = false;
           this.toastService.showError('Error en la comunicación.');
           this.messages.push({ role: 'ai', content: '❌ Hubo un problema al enviar tu mensaje.' });
           this.scrollToBottom();
           this.cdr.detectChanges();
         }
       });
    }
  }

  scrollToBottom() {
    setTimeout(() => {
      if (this.chatScroll) {
        this.chatScroll.nativeElement.scrollTop = this.chatScroll.nativeElement.scrollHeight;
      }
    }, 100);
  }
}