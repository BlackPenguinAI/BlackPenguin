import {
  ChangeDetectorRef,
  Component,
  ElementRef,
  OnDestroy,
  OnInit,
  ViewChild,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { FormsModule } from '@angular/forms';
import { RouterModule } from '@angular/router';
import { TranslateModule, TranslateService } from '@ngx-translate/core';
import { marked } from 'marked';
import { finalize, Subscription } from 'rxjs';

import { SpeechRecognitionService } from '../../core/services/speech-recognition.service';
import {
  CompanyUser,
  CompanyUserInvite,
  CompanyUsersService,
} from '../../core/services/company-users.service';
import { OnboardingQuestion } from '../../shared/ui/onboarding-response-options/onboarding-response-options';
import { OnboardingAiMessageComponent } from '../../shared/ui/onboarding-ai-message/onboarding-ai-message';
import { OnboardingWelcomeComponent } from '../../shared/ui/onboarding-welcome/onboarding-welcome';

import {
  ChatMessage,
  ChatTurnResponse,
  CompanyFieldProgress,
  CompanyProfileResponse,
  EMPTY_COMPANY_PROFILE,
  OnboardingSource,
  OnboardingState,
  Requirement,
  SourceProposal,
  ValidationStatus,
} from './company-onboarding.models';
import { CompanyOnboardingService } from './company-onboarding.service';


@Component({
  selector: 'app-chat',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterModule, TranslateModule, OnboardingAiMessageComponent, OnboardingWelcomeComponent],
  templateUrl: './chat.html',
  styleUrl: './chat.scss',
})
export class ChatComponent implements OnInit, OnDestroy {
  @ViewChild('chatScroll') chatScroll!: ElementRef<HTMLElement>;

  prompt = '';
  isAnalyzing = false;
  currentLang = 'en';
  userName = '';
  isRecording = false;
  readonly speechSupported: boolean;
  isCompleted = false;
  isUploading = false;
  errorMessage = '';
  messages: ChatMessage[] = [];
  sources: OnboardingSource[] = [];
  profile: CompanyProfileResponse = EMPTY_COMPANY_PROFILE;
  showWelcome = false;
  initialState: 'loading' | 'ready' | 'error' = 'loading';
  nextQuestion: OnboardingQuestion | null = null;
  teamUsers: CompanyUser[] = [];
  showTeamSetup = false;
  teamSaving = false;
  teamError = '';
  teamInvite: CompanyUserInvite = {
    first_name: '', last_name: '', email: '', role: 'assistant',
  };
  private readonly markdownCache = new Map<string, string>();
  private readonly speechSubscriptions = new Subscription();
  private speechBase = '';
  private pollingTimer?: ReturnType<typeof setTimeout>;
  private replyToMessageId: string | null = null;
  private lastStateVersion = 0;
  private pollingStartedAt = 0;
  private readonly expandedSourceIds = new Set<string>();
  readonly savingWebsiteSourceIds = new Set<string>();

  constructor(
    private readonly translate: TranslateService,
    private readonly onboarding: CompanyOnboardingService,
    private readonly companyUsers: CompanyUsersService,
    private readonly cdr: ChangeDetectorRef,
    private readonly speech: SpeechRecognitionService,
  ) {
    this.currentLang = localStorage.getItem('bp_lang') || 'en';
    this.translate.use(this.currentLang);
    this.speechSupported = speech.isSupported;
  }

  ngOnInit(): void {
    this.userName = localStorage.getItem('bp_name') || 'User';
    this.syncState();
    this.loadTeam();
    this.speechSubscriptions.add(this.speech.state$.subscribe((state) => {
      this.isRecording = state === 'listening';
      this.cdr.detectChanges();
    }));
    this.speechSubscriptions.add(this.speech.transcript$.subscribe(({ finalText, interimText }) => {
      this.prompt = [this.speechBase, finalText, interimText]
        .filter(Boolean).join(' ').replace(/\s+/g, ' ').trimStart();
      this.cdr.detectChanges();
    }));
    this.speechSubscriptions.add(this.speech.error$.subscribe((message) => {
      this.errorMessage = message;
      this.cdr.detectChanges();
    }));
  }

  ngOnDestroy(): void {
    this.speech.abort();
    this.speechSubscriptions.unsubscribe();
    if (this.pollingTimer) clearTimeout(this.pollingTimer);
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
          this.showWelcome = messages.length === 0 && this.sources.length === 0;
          if (messages.length) {
            this.scrollToBottom();
          }
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
    this.showWelcome = false;
    this.isAnalyzing = true;
    this.onboarding.startChat().pipe(finalize(() => {
      this.isAnalyzing = false;
      this.cdr.detectChanges();
    })).subscribe({
      next: (turn) => {
        this.applyTurn(turn);
        this.schedulePolling();
        this.scrollToBottom();
      },
      error: (error: HttpErrorResponse) => {
        if (error.status !== 401) {
          this.errorMessage = 'The onboarding assistant could not start. Please refresh and try again.';
        }
      },
    });
  }

  beginWithWebsite(url: string): void {
    this.showWelcome = false;
    this.isAnalyzing = true;
    this.onboarding.bootstrap(url).pipe(finalize(() => {
      this.isAnalyzing = false;
      this.cdr.detectChanges();
    })).subscribe({
      next: (turn) => { this.applyTurn(turn); this.schedulePolling(); this.scrollToBottom(); },
      error: () => { this.showWelcome = true; this.errorMessage = 'The website could not be processed. You can retry or continue without it.'; },
    });
  }

  retryInitialState(): void {
    this.initialState = 'loading';
    this.errorMessage = '';
    this.syncState();
  }

  chooseAnswer(value: string, message?: ChatMessage): void { this.prompt = value; this.replyToMessageId = message?.id || null; }
  writeCustomAnswer(message?: ChatMessage): void { this.prompt = ''; this.replyToMessageId = message?.id || null; }
  isActiveQuestion(message: ChatMessage): boolean {
    return !this.hasPendingReview && message.sender === 'ai' && this.hasQuestionPayload(message) && !message.response_payload
      && this.visibleMessages.filter((item) => item.sender === 'ai' && this.hasQuestionPayload(item) && !item.response_payload).at(-1) === message;
  }

  get hasPendingReview(): boolean {
    return this.sources.some((source) => this.hasPendingProposals(source));
  }

  get visibleMessages(): ChatMessage[] {
    if (!this.hasPendingReview) return this.messages;
    return this.messages.filter((message) => !(
      message.sender === 'ai' && !!message.ui_payload && !message.response_payload
    ));
  }

  sourcesForMessage(messageId?: string): OnboardingSource[] {
    return messageId ? this.sources.filter((source) => source.message_id === messageId) : [];
  }

  get unlinkedSources(): OnboardingSource[] {
    const messageIds = new Set(this.messages.flatMap((message) => message.id ? [message.id] : []));
    return this.sources.filter((source) => !source.message_id || !messageIds.has(source.message_id));
  }

  hasPendingProposals(source: OnboardingSource): boolean {
    return source.proposals.some((proposal) => proposal.status === 'pending');
  }

  isSourceExpanded(source: OnboardingSource): boolean {
    return source.status === 'failed'
      || this.hasPendingProposals(source)
      || this.expandedSourceIds.has(source.id);
  }

  onSourceToggle(source: OnboardingSource, event: Event): void {
    if (this.hasPendingProposals(source)) return;
    const details = event.currentTarget as HTMLDetailsElement;
    if (details.open) this.expandedSourceIds.add(source.id);
    else this.expandedSourceIds.delete(source.id);
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
    return this.prompt.trim().length > 0 && !this.isAnalyzing && !this.isCompleted && !this.hasPendingReview;
  }

  get companyAdministrator(): CompanyUser | undefined {
    return this.teamUsers.find(user => user.role === 'admin');
  }

  get invitedTeamCount(): number {
    return this.teamUsers.filter(user => user.role !== 'admin').length;
  }

  loadTeam(): void {
    this.companyUsers.list().subscribe({
      next: users => {
        this.teamUsers = users;
        this.showTeamSetup = users.every(user => user.role === 'admin');
        this.cdr.detectChanges();
      },
      error: () => {
        this.teamError = 'Team setup is temporarily unavailable. You can continue onboarding and use Team later.';
        this.cdr.detectChanges();
      },
    });
  }

  inviteTeamMember(): void {
    if (this.teamSaving || !this.teamInvite.first_name.trim() || !this.teamInvite.last_name.trim() || !this.teamInvite.email.trim()) return;
    this.teamSaving = true;
    this.teamError = '';
    this.companyUsers.invite(this.teamInvite).pipe(finalize(() => {
      this.teamSaving = false;
      this.cdr.detectChanges();
    })).subscribe({
      next: user => {
        this.teamUsers = [...this.teamUsers, user];
        this.teamInvite = { first_name: '', last_name: '', email: '', role: 'assistant' };
      },
      error: (error: HttpErrorResponse) => {
        this.teamError = typeof error.error?.detail === 'string'
          ? error.error.detail
          : 'The team member could not be invited.';
      },
    });
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
    if (this.isRecording) this.speech.stop();
    const content = this.prompt.trim();
    this.prompt = '';
    const optimistic: ChatMessage = { sender: 'user', content, created_at: new Date(), attachments: [] };
    this.messages = [...this.messages, optimistic];
    this.isAnalyzing = true;
    this.scrollToBottom();

    this.errorMessage = '';
    const replyTo = this.replyToMessageId;
    this.replyToMessageId = null;
    this.onboarding.sendMessage(content, replyTo).pipe(finalize(() => {
      this.isAnalyzing = false;
      this.cdr.detectChanges();
    })).subscribe({
        next: (turn) => {
          this.messages = this.messages.filter((message) => message !== optimistic);
          if (turn.field_update_status === 'accepted') this.markReply(replyTo, content);
          this.applyTurn(turn);
          this.scrollToBottom();
        },
        error: (error: HttpErrorResponse) => {
          this.messages = this.messages.filter((message) => message !== optimistic);
          this.prompt = content;
          this.replyToMessageId = replyTo;
          this.errorMessage = this.chatErrorMessage(error);
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
        this.isUploading = false;
        this.mergeSources(sources);
        this.syncState(true);
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
    if (proposal.submitting || proposal.status !== 'pending') return;
    const value = action === 'correct' ? this.parseDraftValue(proposal.draftValue || '') : undefined;
    this.updateProposal(source.id, proposal.id, { submitting: true });
    this.onboarding.decideProposal(proposal.id, action, value).subscribe({
      next: (result) => {
        this.updateProposal(source.id, proposal.id, {
          ...result.proposal,
          draftValue: this.formatValue(result.proposal.value),
          submitting: false,
        });
        this.profile = result.profile;
        this.isCompleted = result.profile.completion.can_complete;
        this.syncState(true);
        this.cdr.detectChanges();
      },
      error: (error: HttpErrorResponse) => {
        if (error.status === 409) {
          this.errorMessage = 'This proposal changed in another request. The current state was reloaded.';
          this.syncState();
        } else {
          this.updateProposal(source.id, proposal.id, { submitting: false });
          this.errorMessage = error.status === 422
            ? 'The proposed value is not valid. Review it and try again.'
            : 'That proposal could not be updated.';
        }
      },
    });
  }

  retrySource(source: OnboardingSource): void {
    if (source.status !== 'failed') return;
    this.errorMessage = '';
    this.onboarding.retrySource(source.id).subscribe({
      next: (updated) => {
        this.mergeSources([updated]);
        this.schedulePolling();
      },
      error: () => {
        this.errorMessage = 'The website could not be queued again. Check its URL or try later.';
      },
    });
  }

  canUseAsOfficialWebsite(source: OnboardingSource): boolean {
    const website = this.profile.data['official_corporate_website'];
    const currentUrl = typeof website === 'string'
      ? website
      : (website && typeof website === 'object' && 'url' in website ? String(website.url || '') : '');
    return (source.status === 'failed' || source.status === 'ready')
      && source.kind === 'official_website'
      && !!source.url
      && currentUrl !== source.url;
  }

  useAsOfficialWebsite(source: OnboardingSource): void {
    if (!this.canUseAsOfficialWebsite(source) || !source.url || this.savingWebsiteSourceIds.has(source.id)) return;
    this.errorMessage = '';
    this.savingWebsiteSourceIds.add(source.id);
    this.onboarding.useUrlAsOfficialWebsite(source.url).subscribe({
      next: (profile) => {
        this.savingWebsiteSourceIds.delete(source.id);
        this.profile = profile;
        this.isCompleted = profile.completion.can_complete;
        this.syncState(true);
      },
      error: () => {
        this.savingWebsiteSourceIds.delete(source.id);
        this.errorMessage = 'The URL could not be saved as the official website.';
        this.cdr.detectChanges();
      },
    });
  }

  formatValue(value: unknown): string {
    if (typeof value === 'string') return value;
    if (value === null || value === undefined) return '';
    return JSON.stringify(value);
  }

  formatBytes(bytes: number | null): string {
    if (bytes == null) return '';
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  downloadAttachment(attachment: { download_url: string | null; name: string }): void {
    if (!attachment.download_url) return;
    this.onboarding.downloadAttachment(attachment.download_url).subscribe({
      next: (blob) => {
        const url = URL.createObjectURL(blob); const anchor = document.createElement('a');
        anchor.href = url; anchor.download = attachment.name; anchor.click(); URL.revokeObjectURL(url);
      },
      error: () => this.errorMessage = 'The attached file could not be downloaded.',
    });
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
    if (!this.speechSupported || this.isAnalyzing || this.isCompleted) return;
    if (this.isRecording) {
      this.speech.stop();
      return;
    }
    this.errorMessage = '';
    this.speechBase = this.prompt.trim();
    this.speech.start(this.currentLang === 'es' ? 'es-PE' : 'en-US');
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
    const merged = new Map(this.sources.map((source) => [source.id, source]));
    for (const source of this.prepareSources(sources)) merged.set(source.id, source);
    this.sources = Array.from(merged.values());
    for (const source of this.sources) {
      if (this.hasPendingProposals(source)) this.expandedSourceIds.add(source.id);
    }
  }

  private syncState(scroll = false): void {
    this.onboarding.getState().subscribe({
      next: (state) => {
        this.initialState = 'ready';
        this.applyState(state);
        if (scroll) this.scrollToBottom();
      },
      error: (error: HttpErrorResponse) => {
        if (error.status !== 401) {
          this.initialState = 'error';
          this.errorMessage = 'The onboarding state could not be synchronized.';
          this.cdr.detectChanges();
        }
      },
    });
  }

  private applyState(state: OnboardingState): void {
    if (state.version < this.lastStateVersion) return;
    this.lastStateVersion = state.version;
    this.messages = [...state.messages];
    this.profile = state.profile;
    this.sources = this.prepareSources(state.sources);
    for (const source of this.sources) {
      if (this.hasPendingProposals(source)) this.expandedSourceIds.add(source.id);
    }
    this.nextQuestion = state.next_question;
    this.isCompleted = state.profile.completion.can_complete;
    this.showWelcome = state.stage === 'website';
    if (this.pollingTimer) clearTimeout(this.pollingTimer);
    if (state.stage === 'processing') this.schedulePolling();
    else this.pollingStartedAt = 0;
    this.cdr.detectChanges();
  }

  private applyTurn(turn: ChatTurnResponse): void {
    const additions = [turn.user_message, turn.message].filter((message): message is ChatMessage => !!message);
    const merged = new Map(this.messages.filter((message) => message.id).map((message) => [message.id!, message]));
    for (const message of additions) {
      if (message.id) merged.set(message.id, message);
      else this.messages = [...this.messages, message];
    }
    const withoutIds = this.messages.filter((message) => !message.id);
    this.messages = [...merged.values(), ...withoutIds];
    this.profile = turn.profile;
    this.isCompleted = turn.profile.completion.can_complete;
    this.nextQuestion = turn.next_question;
    this.mergeSources(turn.sources);
    if (turn.sources.some((source) => source.status === 'processing')) this.schedulePolling();
    this.cdr.detectChanges();
  }

  private schedulePolling(): void {
    if (this.pollingTimer) clearTimeout(this.pollingTimer);
    if (!this.pollingStartedAt) this.pollingStartedAt = Date.now();
    const delay = Date.now() - this.pollingStartedAt > 30_000 ? 5000 : 2000;
    this.pollingTimer = setTimeout(() => this.syncState(true), delay);
  }

  private markReply(messageId: string | null, answer: string): void {
    if (!messageId) return;
    this.messages = this.messages.map((message) => {
      if (message.id !== messageId || !message.ui_payload) return message;
      const options = Array.isArray(message.ui_payload.options) ? message.ui_payload.options : [];
      const examples = Array.isArray(message.ui_payload.examples) ? message.ui_payload.examples : [];
      const choices = options.length ? options : examples;
      const selected = choices.find((item) => item.toLocaleLowerCase() === answer.toLocaleLowerCase()) || null;
      return { ...message, response_payload: { status: 'accepted', answer, selected_option: selected, custom: !selected } };
    });
  }

  private chatErrorMessage(error: HttpErrorResponse): string {
    const detail = typeof error.error?.detail === 'string'
      ? error.error.detail
      : (typeof error.error?.detail?.message === 'string' ? error.error.detail.message : '');
    const requestId = error.headers?.get('X-Request-ID');
    const suffix = requestId ? ` Reference: ${requestId}.` : '';
    if (error.status === 0) return `The message could not reach the server. Check your connection and try again.${suffix}`;
    if (error.status === 422) return `${detail || 'The message is not valid.'}${suffix}`;
    if (error.status === 502) return `The assistant is temporarily unavailable. Your message may have been saved; refresh the conversation before retrying.${suffix}`;
    return `${detail || 'The message could not be completed. Refresh the conversation before retrying.'}${suffix}`;
  }

  private hasQuestionPayload(message: ChatMessage): boolean {
    return !!message.ui_payload
      && typeof message.ui_payload.prompt === 'string'
      && typeof message.ui_payload.label === 'string';
  }

  private updateProposal(sourceId: string, proposalId: string, patch: Partial<SourceProposal>): void {
    this.sources = this.sources.map((source) => source.id !== sourceId ? source : ({
      ...source,
      proposals: source.proposals.map((item) => item.id === proposalId ? { ...item, ...patch } : item),
    }));
    const source = this.sources.find((item) => item.id === sourceId);
    if (source && !this.hasPendingProposals(source)) this.expandedSourceIds.delete(sourceId);
    this.cdr.detectChanges();
  }

  private scrollToBottom(): void {
    setTimeout(() => {
      const element = this.chatScroll?.nativeElement;
      if (element) element.scrollTop = element.scrollHeight;
    }, 100);
  }
}
