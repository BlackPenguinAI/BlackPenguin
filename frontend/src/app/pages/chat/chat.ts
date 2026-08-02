import {
  ChangeDetectorRef,
  Component,
  ElementRef,
  OnInit,
  ViewChild,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { FormsModule } from '@angular/forms';
import { RouterModule } from '@angular/router';
import { TranslateModule, TranslateService } from '@ngx-translate/core';
import { marked } from 'marked';

import {
  ChatMessage,
  CompanyFieldProgress,
  CompanyProfileResponse,
  EMPTY_COMPANY_PROFILE,
  OnboardingSource,
  Requirement,
  SourceProposal,
  ValidationStatus,
} from './company-onboarding.models';
import { CompanyOnboardingService } from './company-onboarding.service';


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
  isUploading = false;
  errorMessage = '';
  messages: ChatMessage[] = [];
  sources: OnboardingSource[] = [];
  profile: CompanyProfileResponse = EMPTY_COMPANY_PROFILE;
  private readonly markdownCache = new Map<string, string>();

  constructor(
    private readonly translate: TranslateService,
    private readonly onboarding: CompanyOnboardingService,
    private readonly cdr: ChangeDetectorRef,
  ) {
    this.currentLang = localStorage.getItem('bp_lang') || 'en';
    this.translate.use(this.currentLang);
  }

  ngOnInit(): void {
    this.userName = localStorage.getItem('bp_name') || 'User';
    this.loadProfile();
    this.loadChatHistory();
    this.loadSources();
  }

  loadProfile(): void {
    this.onboarding.getProfile().subscribe({
        next: (profile) => {
          this.profile = profile;
          this.isCompleted = profile.completion.can_complete;
          this.cdr.detectChanges();
        },
        error: (error: HttpErrorResponse) => {
          if (error.status !== 401) {
            this.errorMessage = 'The company profile could not be loaded.';
          }
        },
      });
  }

  loadChatHistory(): void {
    this.onboarding.getHistory().subscribe({
        next: (messages) => {
          this.messages = messages;
          if (messages.length === 0) this.startConversation();
          else this.scrollToBottom();
        },
        error: (error: HttpErrorResponse) => {
          if (error.status !== 401) {
            this.errorMessage = 'The conversation history could not be loaded.';
          }
        },
      });
  }

  loadSources(): void {
    this.onboarding.getSources().subscribe({
      next: (sources) => (this.sources = this.prepareSources(sources)),
      error: (error: HttpErrorResponse) => {
        if (error.status !== 401) {
          this.errorMessage = 'The onboarding sources could not be loaded.';
        }
      },
    });
  }

  startConversation(): void {
    this.isAnalyzing = true;
    this.onboarding.startChat().subscribe({
      next: (turn) => {
        this.messages.push(turn.message);
        this.profile = turn.profile;
        this.isCompleted = turn.profile.completion.can_complete;
        this.isAnalyzing = false;
        this.scrollToBottom();
      },
      error: (error: HttpErrorResponse) => {
        this.isAnalyzing = false;
        if (error.status !== 401) {
          this.errorMessage = 'The onboarding assistant could not start. Please refresh and try again.';
        }
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

    this.errorMessage = '';
    this.onboarding.sendMessage(content).subscribe({
        next: (turn) => {
          this.messages.push(turn.message);
          this.profile = turn.profile;
          this.isCompleted = turn.profile.completion.can_complete;
          this.mergeSources(turn.sources);
          this.isAnalyzing = false;
          this.scrollToBottom();
        },
        error: () => {
          this.isAnalyzing = false;
          this.errorMessage = 'I could not send that message. Your profile was not changed.';
          this.cdr.detectChanges();
        },
      });
  }

  renderMarkdown(content: string): string {
    const cached = this.markdownCache.get(content);
    if (cached) return cached;
    const rendered = marked.parse(content, { async: false, breaks: true }) as string;
    this.markdownCache.set(content, rendered);
    return rendered;
  }

  onFilesSelected(event: Event): void {
    const input = event.target as HTMLInputElement;
    const files = Array.from(input.files || []);
    input.value = '';
    if (!files.length || this.isUploading) return;
    this.errorMessage = '';
    this.isUploading = true;
    this.onboarding.uploadFiles(files).subscribe({
      next: (sources) => {
        this.mergeSources(sources);
        this.isUploading = false;
        const ready = sources.filter((source) => source.status === 'ready').length;
        const failed = sources.length - ready;
        const summary = [
          ready ? `${ready} source${ready === 1 ? '' : 's'} ready for review` : '',
          failed ? `${failed} could not be processed` : '',
        ].filter(Boolean).join('; ');
        this.messages.push({
          sender: 'ai',
          content: `**Document review:** ${summary}. Please review the proposed details below.`,
          created_at: new Date(),
        });
        this.scrollToBottom();
      },
      error: () => {
        this.isUploading = false;
        this.errorMessage = 'The files could not be uploaded. Use PDF, DOCX, or TXT files up to 15 MB each.';
      },
    });
  }

  decideProposal(
    source: OnboardingSource,
    proposal: SourceProposal,
    action: 'confirm' | 'correct' | 'reject',
  ): void {
    const value = action === 'correct' ? this.parseDraftValue(proposal.draftValue || '') : undefined;
    this.onboarding.decideProposal(proposal.id, action, value).subscribe({
      next: (result) => {
        const index = source.proposals.findIndex((item) => item.id === proposal.id);
        if (index >= 0) source.proposals[index] = {
          ...result.proposal,
          draftValue: this.formatValue(result.proposal.value),
        };
        this.profile = result.profile;
        this.isCompleted = result.profile.completion.can_complete;
      },
      error: () => {
        this.errorMessage = 'That proposal could not be updated. It may already have been reviewed.';
      },
    });
  }

  formatValue(value: unknown): string {
    if (typeof value === 'string') return value;
    if (value === null || value === undefined) return '';
    return JSON.stringify(value);
  }

  private parseDraftValue(value: string): unknown {
    const trimmed = value.trim();
    if (/^[\[{]/.test(trimmed)) {
      try {
        return JSON.parse(trimmed);
      } catch {
        return trimmed;
      }
    }
    return trimmed;
  }

  toggleRecording(): void {
    this.isRecording = !this.isRecording;
  }

  trackField(_: number, field: CompanyFieldProgress): string {
    return field.key;
  }

  trackSource(_: number, source: OnboardingSource): string {
    return source.id;
  }

  private prepareSources(sources: OnboardingSource[]): OnboardingSource[] {
    return sources.map((source) => ({
      ...source,
      proposals: source.proposals.map((proposal) => ({
        ...proposal,
        draftValue: this.formatValue(proposal.value),
      })),
    }));
  }

  private mergeSources(sources: OnboardingSource[]): void {
    for (const source of this.prepareSources(sources)) {
      const index = this.sources.findIndex((item) => item.id === source.id);
      if (index >= 0) this.sources[index] = source;
      else this.sources.unshift(source);
    }
  }

  private scrollToBottom(): void {
    setTimeout(() => {
      const element = this.chatScroll?.nativeElement;
      if (element) element.scrollTop = element.scrollHeight;
    }, 100);
  }
}
