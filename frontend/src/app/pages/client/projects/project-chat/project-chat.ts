import { Component, OnInit, ChangeDetectorRef, ViewChild, ElementRef, isDevMode } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterModule } from '@angular/router';
import { HttpClient, HttpHeaders } from '@angular/common/http';

@Component({
  selector: 'app-project-chat',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterModule],
  templateUrl: './project-chat.html',
  styleUrls: ['./project-chat.scss']
})
export class ProjectChatComponent implements OnInit {
  @ViewChild('chatScroll') chatScroll!: ElementRef;

  projectId: string = '';
  prompt: string = '';
  isAnalyzing: boolean = false;
  messages: any[] = [];
  
  // Perfil del Proyecto (3 Pilares)
  profile = {
    is_technical_completed: false,
    is_commercial_completed: false,
    is_inventory_completed: false,
    is_fully_completed: false
  };

  private baseUrl = isDevMode() ? 'http://localhost:8000/api/v1/properties' : 'https://blackpenguin.ai/api/v1/properties';

  constructor(private route: ActivatedRoute, private http: HttpClient, private cdr: ChangeDetectorRef) {}

  ngOnInit(): void {
    this.projectId = this.route.snapshot.paramMap.get('id') || '';
    this.loadHistory();
    this.loadProfile();
  }

  private getHeaders() {
    return { headers: new HttpHeaders({ 'Authorization': `Bearer ${localStorage.getItem('bp_token')}` }) };
  }

  loadHistory() {
    this.http.get<any[]>(`${this.baseUrl}/${this.projectId}/chat`, this.getHeaders()).subscribe({
      next: (history) => {
        this.messages = history;
        this.scrollToBottom();
      }
    });
  }

  loadProfile() {
    // Al listar los proyectos viene el profile, aquí hacemos un filtrado rápido para obtener el estatus
    this.http.get<any[]>(this.baseUrl, this.getHeaders()).subscribe({
      next: (projects) => {
        const currentProject = projects.find(p => p.id === this.projectId);
        if (currentProject && currentProject.profile) {
          this.profile = currentProject.profile;
        }
      }
    });
  }

  sendMessage() {
    if (!this.prompt.trim() || this.isAnalyzing) return;
    
    const userText = this.prompt;
    this.prompt = '';
    this.messages.push({ sender: 'user', content: userText });
    this.isAnalyzing = true;
    this.scrollToBottom();

    // NOTA: Este POST irá a un endpoint de IA que debes completar en tu backend, 
    // por ahora enviamos el texto simulando el flujo.
    this.http.post<any>(`${this.baseUrl}/${this.projectId}/chat`, { message: userText }, this.getHeaders()).subscribe({
      next: (response) => {
        this.messages.push(response);
        this.isAnalyzing = false;
        this.scrollToBottom();
        this.loadProfile(); // Refresca los pilares
      },
      error: () => {
        this.isAnalyzing = false;
      }
    });
  }

  scrollToBottom() {
    setTimeout(() => {
      if (this.chatScroll) {
        this.chatScroll.nativeElement.scrollTop = this.chatScroll.nativeElement.scrollHeight;
      }
    }, 100);
  }
}