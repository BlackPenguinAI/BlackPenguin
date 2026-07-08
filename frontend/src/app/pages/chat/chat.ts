import { Component, ElementRef, ViewChild, ChangeDetectorRef } from '@angular/core'; 
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
  currentLang: string = 'en';
  userName: string = '';

  selectedFile: File | null = null;
  isDragOver: boolean = false;
  messages: { role: 'user' | 'ai', content: string, file?: string }[] = [];

  sessionId: string = ''; 

  constructor(
    private translate: TranslateService,
    private chatService: ChatService,
    private toastService: ToastService,
    private cdr: ChangeDetectorRef 
  ) {
    this.currentLang = this.translate.currentLang || localStorage.getItem('bp_lang') || 'en';
    this.userName = localStorage.getItem('bp_name') || 'Admin';
  }

  // --- MÉTODOS DE IDIOMAS ---
  switchLanguage(lang: string) {
    this.translate.use(lang);
    this.currentLang = lang;
    localStorage.setItem('bp_lang', lang);
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
        this.cdr.detectChanges(); 
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

    const userMessage = this.prompt.trim() || 'Por favor procesa los datos y dime qué encontraste.';
    this.messages.push({ role: 'user', content: userMessage, file: this.selectedFile?.name });
    
    const currentPrompt = this.prompt;
    this.prompt = '';
    this.isAnalyzing = true;
    this.scrollToBottom();
    this.cdr.detectChanges(); 

    if (this.selectedFile) {
       this.chatService.analyzeDocument(this.sessionId, this.selectedFile, currentPrompt).subscribe({
         next: (res) => {
           this.isAnalyzing = false;
           this.messages.push({ role: 'ai', content: res.message });
           this.selectedFile = null; 
           this.scrollToBottom();
           this.cdr.detectChanges(); 
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
       const history = this.messages.map(m => ({ 
         role: m.role === 'ai' ? 'assistant' : m.role, 
         content: m.content 
       }));
       
       this.chatService.sendMessage(this.sessionId, history).subscribe({
         next: (res) => {
           this.isAnalyzing = false;
           this.messages.push({ role: 'ai', content: res.message });
           this.scrollToBottom();
           this.cdr.detectChanges(); 
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