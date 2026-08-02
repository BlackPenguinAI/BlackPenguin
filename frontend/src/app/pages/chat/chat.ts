import {
  ChangeDetectorRef,
  Component,
  ElementRef,
  OnInit,
  ViewChild,
  isDevMode,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { RouterModule } from '@angular/router';
import { TranslateModule, TranslateService } from '@ngx-translate/core';

import {
  ChatMessage,
  CompanyFieldProgress,
  CompanyProfileResponse,
  EMPTY_COMPANY_PROFILE,
  Requirement,
  ValidationStatus,
} from './company-onboarding.models';


@Component({
  selector: 'app-chat',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterModule, TranslateModule],
  templateUrl: './chat.html',
  styleUrl: './chat.scss',
})
export class ChatComponent implements OnInit {
  @ViewChild('chatScroll') chatScroll!: ElementRef<HTMLElement>;

  prompt = '';
  isAnalyzing = false;
  currentLang = 'en';
  userName = '';
  isRecording = false;
  isCompleted = false;
  messages: ChatMessage[] = [];
  profile: CompanyProfileResponse = EMPTY_COMPANY_PROFILE;

  constructor(
    private readonly translate: TranslateService,
    private readonly http: HttpClient,
    private readonly cdr: ChangeDetectorRef,
  ) {
    this.currentLang = localStorage.getItem('bp_lang') || 'en';
    this.translate.use(this.currentLang);
  }

  private get baseUrl(): string {
    return isDevMode()
      ? 'http://localhost:8000/api/v1/company-onboarding'
      : '/api/v1/company-onboarding';
  }

  private get headers(): HttpHeaders {
    const token = localStorage.getItem('bp_token');
    return token
      ? new HttpHeaders().set('Authorization', `Bearer ${token}`)
      : new HttpHeaders();
  }

  ngOnInit(): void {
    this.userName = localStorage.getItem('bp_name') || 'User';
    this.loadProfile();
    this.loadChatHistory();
  }

  loadProfile(): void {
    this.http
      .get<CompanyProfileResponse>(`${this.baseUrl}/profile`, { headers: this.headers })
      .subscribe({
        next: (profile) => {
          this.profile = profile;
          this.isCompleted = profile.completion.can_complete;
          this.cdr.detectChanges();
        },
      });
  }

  loadChatHistory(): void {
    this.http
      .get<ChatMessage[]>(`${this.baseUrl}/chat`, { headers: this.headers })
      .subscribe({
        next: (messages) => {
          this.messages = messages;
          this.scrollToBottom();
        },
      });
  }

  fieldsByRequirement(requirement: Requirement): CompanyFieldProgress[] {
    return this.profile.fields.filter((field) => field.requirement === requirement);
  }

  get requiredFields(): CompanyFieldProgress[] {
    return this.fieldsByRequirement('required');
  }

  get conditionalFields(): CompanyFieldProgress[] {
    return this.fieldsByRequirement('conditionally_required');
  }

  get canSend(): boolean {
    return this.prompt.trim().length > 0 && !this.isAnalyzing && !this.isCompleted;
  }

  statusIcon(status: ValidationStatus): string {
    const icons: Record<ValidationStatus, string> = {
      confirmed: 'check_circle',
      corrected_by_user: 'check_circle',
      not_applicable: 'remove_circle',
      conflicting: 'error',
      pending_confirmation: 'schedule',
      extracted: 'manage_search',
      missing: 'radio_button_unchecked',
    };
    return icons[status];
  }

  statusClass(status: ValidationStatus): string {
    if (status === 'confirmed' || status === 'corrected_by_user') return 'text-green-500';
    if (status === 'conflicting') return 'text-red-400';
    if (status === 'pending_confirmation' || status === 'extracted') return 'text-secondary';
    return 'text-gray-600';
  }

  statusLabel(status: ValidationStatus): string {
    const labels: Record<ValidationStatus, string> = {
      missing: 'Missing',
      extracted: 'Extracted',
      pending_confirmation: 'Pending confirmation',
      confirmed: 'Confirmed',
      corrected_by_user: 'Corrected by user',
      conflicting: 'Conflicting',
      not_applicable: 'Not applicable',
    };
    return labels[status];
  }

  handleKeyDown(event: KeyboardEvent): void {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      if (this.canSend) this.sendMessage();
    }
  }

  sendMessage(): void {
    if (!this.canSend) return;
    const content = this.prompt.trim();
    this.prompt = '';
    this.messages.push({ sender: 'user', content, created_at: new Date() });
    this.isAnalyzing = true;
    this.scrollToBottom();

    this.http
      .post<ChatMessage>(`${this.baseUrl}/chat`, { message: content }, { headers: this.headers })
      .subscribe({
        next: (message) => {
          this.messages.push(message);
          this.isAnalyzing = false;
          this.loadProfile();
          this.scrollToBottom();
        },
        error: () => {
          this.isAnalyzing = false;
          this.cdr.detectChanges();
        },
      });
  }

  toggleRecording(): void {
    this.isRecording = !this.isRecording;
  }

  trackField(_: number, field: CompanyFieldProgress): string {
    return field.key;
  }

  private scrollToBottom(): void {
    setTimeout(() => {
      const element = this.chatScroll?.nativeElement;
      if (element) element.scrollTop = element.scrollHeight;
    }, 100);
  }
}
