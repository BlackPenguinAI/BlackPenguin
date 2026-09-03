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
import { Router, RouterModule } from '@angular/router';
import { TranslateModule, TranslateService } from '@ngx-translate/core';
import { marked } from 'marked';
import { catchError, concatMap, finalize, from, of, Subscription, tap, toArray } from 'rxjs';

import { SpeechRecognitionService } from '../../core/services/speech-recognition.service';
import { deviceTimezone } from '../../core/timezones';
import { OnboardingQuestion } from '../../shared/ui/onboarding-response-options/onboarding-response-options';
import { OnboardingAiMessageComponent } from '../../shared/ui/onboarding-ai-message/onboarding-ai-message';
import { OnboardingWelcomeComponent } from '../../shared/ui/onboarding-welcome/onboarding-welcome';
import { TimezoneSelectComponent } from '../../shared/ui/timezone-select/timezone-select';
import {
  captureReviewScrollAnchor,
  isNearScrollBottom,
  OnboardingScrollMode,
  restoreReviewScrollAnchor,
  ReviewScrollAnchor,
} from '../../shared/utils/review-scroll-anchor';

import {
  ChatMessage,
  ChatTurnResponse,
  CompanyFieldProgress,
  CompanyProfileResponse,
  EMPTY_COMPANY_PROFILE,
  EMPTY_TEAM_ONBOARDING,
  OnboardingSource,
  OnboardingStage,
  OnboardingState,
  Requirement,
  SourceProposal,
  ValidationStatus,
  TeamMemberInvite,
  TeamOnboarding,
  CompanyMediaAsset,
  TeamRoleStatus,
  TeamProjectOption,
} from './company-onboarding.models';
import { CompanyOnboardingService } from './company-onboarding.service';


@Component({
  selector: 'app-chat',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterModule, TranslateModule, OnboardingAiMessageComponent, OnboardingWelcomeComponent, TimezoneSelectComponent],
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
  currentStage: OnboardingStage = 'website';
  team: TeamOnboarding = EMPTY_TEAM_ONBOARDING;
  teamSaving = false;
  teamSavingAction: 'add' | 'continue' | null = null;
  teamError = '';
  teamSuccess = '';
  readonly teamMemberBusyIds = new Set<string>();
  teamInviteAttempted = false;
  publicEmails = '';
  publicPhones = '';
  socialProfiles = '';
  publicPresenceSaving = false;
  publicPresenceSaved = false;
  publicPresenceError = '';
  readonly publicPresenceDirty = new Set<string>();
  readonly publicPresenceEditing = new Set<string>();
  companyMedia: CompanyMediaAsset[] = [];
  selectedLogoId: string | null = null;
  logoBusy = false;
  readonly companyMediaUrls = new Map<string, string>();
  teamInvite: TeamMemberInvite = {
    first_name: '', last_name: '', email: '', role: 'assistant',
    timezone: deviceTimezone(), project_access_scope: 'all', project_ids: [],
  };
  teamProjects: TeamProjectOption[] = [];
  private readonly markdownCache = new Map<string, string>();
  private readonly speechSubscriptions = new Subscription();
  private speechBase = '';
  private pollingTimer?: ReturnType<typeof setTimeout>;
  private replyToMessageId: string | null = null;
  private lastStateVersion = 0;
  private teamInviteRequestKey = '';
  private teamInviteRequestFingerprint = '';
  private pollingStartedAt = 0;
  private readonly expandedSourceIds = new Set<string>();
  readonly savingWebsiteSourceIds = new Set<string>();
  readonly confirmingSourceIds = new Set<string>();

  constructor(
    private readonly translate: TranslateService,
    private readonly onboarding: CompanyOnboardingService,
    private readonly cdr: ChangeDetectorRef,
    private readonly speech: SpeechRecognitionService,
    private readonly router: Router,
  ) {
    this.currentLang = localStorage.getItem('bp_lang') || 'en';
    this.translate.use(this.currentLang);
    this.speechSupported = speech.isSupported;
  }

  ngOnInit(): void {
    this.userName = localStorage.getItem('bp_name') || 'User';
    this.syncState();
    this.loadCompanyMedia();
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
    for (const url of this.companyMediaUrls.values()) URL.revokeObjectURL(url);
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

  loadCompanyMedia(): void {
    this.onboarding.getMedia().subscribe({ next: items => {
      this.companyMedia = items;
      if (!this.selectedLogoId) this.selectedLogoId = items.find(item => item.is_primary)?.id || null;
      for (const item of items) {
        if (this.companyMediaUrls.has(item.id)) continue;
        this.onboarding.downloadAttachment(item.image_url).subscribe({ next: blob => {
          this.companyMediaUrls.set(item.id, URL.createObjectURL(blob)); this.cdr.detectChanges();
        }});
      }
      this.cdr.detectChanges();
    }});
  }

  uploadCompanyLogo(event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0]; if (!file || this.logoBusy) return;
    this.logoBusy = true;
    this.onboarding.uploadLogo(file).subscribe({
      next: asset => {
        this.logoBusy = false;
        input.value = '';
        this.selectedLogoId = asset.id;
        this.loadCompanyMedia();
        this.cdr.detectChanges();
      },
      error: () => { this.logoBusy = false; this.errorMessage = 'Upload a valid JPG, PNG, or WEBP logo up to 5 MB.'; },
    });
  }

  selectCompanyLogo(asset: CompanyMediaAsset): void {
    if (this.logoBusy) return;
    this.selectedLogoId = asset.id;
    this.errorMessage = '';
    this.cdr.detectChanges();
  }

  confirmCompanyLogo(): void {
    if (this.logoBusy || !this.selectedLogoId) return;
    this.logoBusy = true;
    this.onboarding.selectLogo(this.selectedLogoId).subscribe({
      next: () => { this.logoBusy = false; this.loadCompanyMedia(); this.syncState('bottom'); },
      error: () => { this.logoBusy = false; this.errorMessage = 'That image could not be selected as the Company logo.'; },
    });
  }

  deferCompanyLogo(): void {
    this.logoBusy = true;
    this.onboarding.deferLogo().subscribe({
      next: profile => { this.logoBusy = false; this.profile = profile; this.selectedLogoId = null; this.syncState('bottom'); },
      error: () => { this.logoBusy = false; this.errorMessage = 'The logo step could not be deferred.'; },
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
    return !this.hasPendingReview && !this.hasExclusiveStep && message.sender === 'ai' && this.hasQuestionPayload(message) && !message.response_payload
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
    return this.prompt.trim().length > 0 && !this.isAnalyzing
      && !this.hasPendingReview && !this.hasExclusiveStep;
  }

  get hasExclusiveStep(): boolean {
    return this.currentStage === 'logo_review' || this.currentStage === 'team' || this.currentStage === 'enrichment';
  }

  get hasProcessingSources(): boolean {
    return this.currentStage === 'processing' || this.sources.some(source => source.status === 'processing');
  }

  get teamInviteErrors(): Record<string, string> {
    const errors: Record<string, string> = {};
    if (!this.teamInvite.first_name.trim()) errors['first_name'] = 'Enter the first name.';
    if (!this.teamInvite.last_name.trim()) errors['last_name'] = 'Enter the last name.';
    if (!this.teamInvite.email.trim()) errors['email'] = 'Enter an email address.';
    else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(this.teamInvite.email.trim())) errors['email'] = 'Enter a valid email address.';
    if (this.teamInvite.project_access_scope === 'selected' && !(this.teamInvite.project_ids || []).length) errors['project_ids'] = 'Select at least one Project.';
    return errors;
  }

  get teamInviteErrorCount(): number { return Object.keys(this.teamInviteErrors).length; }
  get canInviteTeamMember(): boolean { return !this.teamSaving && this.teamInviteErrorCount === 0; }

  publicPresenceFieldError(field: string): string {
    if (!this.editablePublicPresenceFields.includes(field)) return '';
    const values = field === 'public_contact_emails' ? this.splitList(this.publicEmails)
      : field === 'public_contact_phones' ? this.splitList(this.publicPhones)
      : this.splitList(this.socialProfiles);
    if (!values.length) return '';
    if (field === 'public_contact_emails' && values.some(value => !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value))) {
      return 'Enter complete public email addresses.';
    }
    if (field === 'public_contact_phones' && values.some(value => value.replace(/\D/g, '').length < 7)) {
      return 'Enter public phone numbers with at least 7 digits.';
    }
    if (field === 'corporate_social_profiles' && values.some(value => !/^https?:\/\/[^\s.]+\.[^\s]+$/i.test(value))) {
      return 'Enter complete HTTP or HTTPS social profile URLs.';
    }
    return '';
  }

  get publicPresenceErrorCount(): number {
    const invalid = this.editablePublicPresenceFields.filter(field => !!this.publicPresenceFieldError(field)).length;
    const hasValue = this.editablePublicPresenceFields.some(field => {
      const value = field === 'public_contact_emails' ? this.publicEmails
        : field === 'public_contact_phones' ? this.publicPhones : this.socialProfiles;
      return this.splitList(value).length > 0;
    });
    return invalid + (hasValue ? 0 : 1);
  }

  get canSavePublicPresence(): boolean {
    return !this.publicPresenceSaving && this.editablePublicPresenceFields.length > 0 && this.publicPresenceErrorCount === 0;
  }

  inviteTeamMember(): void {
    this.teamInviteAttempted = true;
    this.teamSuccess = '';
    if (this.currentStage !== 'team' || this.hasPendingReview || this.isCompleted || !this.canInviteTeamMember) return;
    this.teamSaving = true;
    this.teamSavingAction = 'add';
    this.teamError = '';
    const submittedEmail = this.teamInvite.email.trim();
    const requestKey = this.teamInvitationRequestKey();
    this.onboarding.createTeamMember(this.teamInvite, requestKey).pipe(finalize(() => {
      this.teamSaving = false;
      this.teamSavingAction = null;
      this.cdr.detectChanges();
    })).subscribe({
      next: member => {
        if (member.invitation_delivery === 'failed' || member.auth_status === 'provisioning_failed') {
          const code = member.invitation_error_code ? ` (${member.invitation_error_code})` : '';
          this.teamError = `The user ${submittedEmail} was saved, but Firebase did not accept the invitation${code}. Use Resend invitation or revoke the failed user below.`;
          this.teamSuccess = '';
        } else {
          this.teamSuccess = member.request_replayed
            ? `The invitation for ${submittedEmail} was already processed.`
            : `Invitation sent to ${submittedEmail}. The user is pending activation.`;
        }
        this.teamInvite = { first_name: '', last_name: '', email: '', role: 'assistant',
          timezone: deviceTimezone(), project_access_scope: 'all', project_ids: [] };
        this.teamInviteAttempted = false;
        this.teamInviteRequestKey = '';
        this.teamInviteRequestFingerprint = '';
        this.refreshTeam(true);
      },
      error: (error: HttpErrorResponse) => {
        const detail = error.error?.detail;
        this.teamError = typeof detail === 'string'
          ? detail
          : detail?.message || 'The team member could not be invited.';
        if (detail?.code === 'USER_ALREADY_INVITED') this.refreshTeam(true);
      },
    });
  }

  private teamInvitationRequestKey(): string {
    const fingerprint = JSON.stringify({
      ...this.teamInvite,
      first_name: this.teamInvite.first_name.trim(),
      last_name: this.teamInvite.last_name.trim(),
      email: this.teamInvite.email.trim().toLowerCase(),
      project_ids: [...(this.teamInvite.project_ids || [])].sort(),
    });
    if (!this.teamInviteRequestKey || fingerprint !== this.teamInviteRequestFingerprint) {
      const random = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`;
      this.teamInviteRequestKey = `company-onboarding-user-${random}`;
      this.teamInviteRequestFingerprint = fingerprint;
    }
    return this.teamInviteRequestKey;
  }

  teamProjectSelected(projectId: string): boolean { return (this.teamInvite.project_ids || []).includes(projectId); }
  toggleTeamProject(projectId: string, selected: boolean): void {
    this.teamInvite.project_ids = selected
      ? [...new Set([...(this.teamInvite.project_ids || []), projectId])]
      : (this.teamInvite.project_ids || []).filter(id => id !== projectId);
  }

  savePublicPresence(): void {
    if (this.currentStage !== 'enrichment' || this.hasPendingReview || this.isCompleted || !this.canSavePublicPresence) return;
    const emails = this.splitList(this.publicEmails);
    const phones = this.splitList(this.publicPhones);
    const socialProfiles = this.splitList(this.socialProfiles);
    const fields = this.editablePublicPresenceFields;
    if (!fields.length) return;
    const valuesByField: Record<string, string[]> = {
      public_contact_emails: emails,
      public_contact_phones: phones,
      corporate_social_profiles: socialProfiles,
    };
    if (fields.every(field => !valuesByField[field].length)) {
      this.publicPresenceError = 'Enter at least one public email, phone number, or social profile.';
      return;
    }
    this.publicPresenceSaving = true;
    this.publicPresenceSaved = false;
    this.publicPresenceError = '';
    this.onboarding.savePublicPresence(emails, phones, socialProfiles, fields).pipe(finalize(() => {
      this.publicPresenceSaving = false;
      this.cdr.detectChanges();
    })).subscribe({
      next: profile => {
        this.profile = profile;
        fields.forEach(field => { this.publicPresenceDirty.delete(field); this.publicPresenceEditing.delete(field); });
        this.publicPresenceSaved = true;
        this.syncState('bottom');
      },
      error: (error: HttpErrorResponse) => {
        this.publicPresenceError = this.proposalErrorMessage(error);
      },
    });
  }

  deferPublicPresence(): void {
    if (this.currentStage !== 'enrichment' || this.publicPresenceSaving || this.isCompleted) return;
    const fields = this.editablePublicPresenceFields;
    if (!fields.length) return;
    this.publicPresenceSaving = true;
    this.publicPresenceError = '';
    this.onboarding.deferPublicPresence(fields).pipe(finalize(() => {
      this.publicPresenceSaving = false;
      this.cdr.detectChanges();
    })).subscribe({
      next: profile => { this.profile = profile; this.syncState('bottom'); },
      error: (error: HttpErrorResponse) => this.publicPresenceError = this.proposalErrorMessage(error),
    });
  }

  continueTeamSetup(): void {
    if (this.currentStage !== 'team' || this.teamSaving || this.hasPendingReview || this.isCompleted) return;
    this.teamSaving = true;
    this.teamSavingAction = 'continue';
    this.teamError = '';
    this.onboarding.continueTeamSetup().pipe(finalize(() => {
      this.teamSaving = false;
      this.teamSavingAction = null;
      this.cdr.detectChanges();
    })).subscribe({
      next: state => { this.applyState(state); this.scrollToBottom(); },
      error: (error: HttpErrorResponse) => {
        this.teamError = typeof error.error?.detail === 'string'
          ? error.error.detail
          : 'The onboarding could not continue. Please try again.';
      },
    });
  }

  resendTeamMember(memberId: string): void {
    if (this.teamMemberBusyIds.has(memberId)) return;
    this.teamMemberBusyIds.add(memberId);
    this.teamError = '';
    this.onboarding.resendTeamMember(memberId).pipe(finalize(() => {
      this.teamMemberBusyIds.delete(memberId);
      this.cdr.detectChanges();
    })).subscribe({
      next: () => {
        this.teamSuccess = 'Firebase accepted the new activation request.';
        this.refreshTeam(true);
      },
      error: (error: HttpErrorResponse) => {
        this.teamError = typeof error.error?.detail === 'string'
          ? error.error.detail
          : 'The activation request could not be resent.';
      },
    });
  }

  revokeTeamMember(memberId: string): void {
    if (this.teamMemberBusyIds.has(memberId)) return;
    this.teamMemberBusyIds.add(memberId);
    this.teamError = '';
    this.onboarding.revokeTeamMember(memberId).pipe(finalize(() => {
      this.teamMemberBusyIds.delete(memberId);
      this.cdr.detectChanges();
    })).subscribe({
      next: () => {
        this.teamSuccess = 'The failed invitation was removed. The email can be invited again.';
        this.refreshTeam(true);
      },
      error: (error: HttpErrorResponse) => {
        this.teamError = typeof error.error?.detail === 'string'
          ? error.error.detail
          : 'The failed invitation could not be removed.';
      },
    });
  }

  teamStatusIcon(status: TeamRoleStatus): string {
    return ({
      confirmed: 'check_circle', deferred: 'schedule', not_applicable: 'remove_circle', missing: 'radio_button_unchecked',
    } as Record<TeamRoleStatus, string>)[status];
  }

  teamStatusClass(status: TeamRoleStatus): string {
    if (status === 'confirmed') return 'text-green-500';
    if (status === 'deferred') return 'text-secondary';
    return 'text-gray-600';
  }

  teamStatusLabel(status: TeamRoleStatus): string {
    return ({
      confirmed: 'Configured', deferred: 'Configure later', not_applicable: 'Not needed now', missing: 'Pending decision',
    } as Record<TeamRoleStatus, string>)[status];
  }

  statusIcon(status: ValidationStatus): string {
    const icons: Record<ValidationStatus, string> = {
      confirmed: 'check_circle',
      corrected_by_user: 'check_circle',
      not_applicable: 'remove_circle',
      deferred: 'schedule',
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
    if (status === 'pending_confirmation' || status === 'extracted' || status === 'deferred') return 'text-secondary';
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
      deferred: 'Provide later',
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
    const replyTo = this.replyToMessageId || this.activeQuestionMessageId();
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
        this.syncState('bottom');
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
    const anchor = captureReviewScrollAnchor(this.chatScroll?.nativeElement, proposal.id);
    const nextProposalId = source.proposals.find(item => item.status === 'pending' && item.id !== proposal.id)?.id || null;
    this.errorMessage = '';
    const value = action === 'correct'
      ? this.parseDraftValue(proposal.field, proposal.draftValue || '')
      : undefined;
    this.updateProposal(source.id, proposal.id, { submitting: true, errorMessage: undefined });
    this.onboarding.decideProposal(proposal.id, action, value).subscribe({
      next: (result) => {
        this.updateProposal(source.id, proposal.id, {
          ...result.proposal,
          draftValue: this.formatProposalValue(result.proposal),
          submitting: false,
          errorMessage: undefined,
        });
        this.profile = result.profile;
        this.isCompleted = result.profile.completion.can_complete;
        const pendingRemain = this.sources.some(item => this.hasPendingProposals(item));
        if (pendingRemain) this.restoreProposalContext(anchor, nextProposalId);
        else this.syncState('preserve', anchor);
        this.cdr.detectChanges();
      },
      error: (error: HttpErrorResponse) => {
        if (error.status === 409) {
          this.errorMessage = 'This proposal changed in another request. The current state was reloaded.';
          this.syncState('preserve', anchor);
        } else {
          const message = error.status === 422
            ? this.proposalErrorMessage(error)
            : 'That proposal could not be updated.';
          this.updateProposal(source.id, proposal.id, { submitting: false, errorMessage: message });
          this.restoreProposalAnchor(anchor);
        }
      },
    });
  }

  confirmAllUnchanged(source: OnboardingSource): void {
    const pending = source.proposals.filter(proposal => proposal.status === 'pending' && !proposal.submitting);
    if (!pending.length || this.confirmingSourceIds.has(source.id)) return;
    const anchor = captureReviewScrollAnchor(this.chatScroll?.nativeElement, pending[0].id);
    this.confirmingSourceIds.add(source.id);
    for (const proposal of pending) {
      this.updateProposal(source.id, proposal.id, { submitting: true, errorMessage: undefined });
    }
    from(pending).pipe(
      concatMap(proposal => this.onboarding.decideProposal(proposal.id, 'confirm').pipe(
        tap(result => {
          this.updateProposal(source.id, proposal.id, {
            ...result.proposal,
            draftValue: this.formatProposalValue(result.proposal),
            submitting: false,
            errorMessage: undefined,
          });
          this.profile = result.profile;
        }),
        catchError((error: HttpErrorResponse) => {
          this.updateProposal(source.id, proposal.id, {
            submitting: false,
            errorMessage: this.proposalErrorMessage(error),
          });
          return of(null);
        }),
      )),
      toArray(),
      finalize(() => {
        this.confirmingSourceIds.delete(source.id);
        this.syncState('preserve', anchor);
        this.cdr.detectChanges();
      }),
    ).subscribe();
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
        this.syncState('auto');
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

  formatProposalValue(proposal: Pick<SourceProposal, 'field' | 'value'>): string {
    if (proposal.field === 'official_corporate_website'
      && proposal.value && typeof proposal.value === 'object') {
      const website = proposal.value as { exists?: boolean; url?: unknown };
      if (website.exists === false) return 'No official website';
      if (typeof website.url === 'string') return website.url;
    }
    if (Array.isArray(proposal.value)) return proposal.value.map(String).join(', ');
    return this.formatValue(proposal.value);
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

  private parseDraftValue(field: string, value: string): unknown {
    const trimmed = value.trim();
    if (field === 'official_corporate_website') {
      if (/^(no official website|no website|none|no)$/i.test(trimmed)) {
        return { exists: false, url: null };
      }
      return { exists: true, url: trimmed };
    }
    if (['public_contact_emails', 'public_contact_phones', 'corporate_social_profiles'].includes(field)) {
      return this.splitList(trimmed);
    }
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
    if (!this.speechSupported || this.isAnalyzing) return;
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

  trackProposal(_: number, proposal: SourceProposal): string {
    return proposal.id;
  }

  private prepareSources(sources: OnboardingSource[]): OnboardingSource[] {
    const previousProposals = new Map(
      this.sources.flatMap((source) => source.proposals.map((proposal) => [proposal.id, proposal] as const)),
    );
    return sources.map((source) => ({
      ...source,
      proposals: source.proposals.map((proposal) => {
        const previous = previousProposals.get(proposal.id);
        const preserveDraft = proposal.status === 'pending'
          && previous?.status === 'pending'
          && previous.draftValue !== undefined;
        return {
          ...proposal,
          draftValue: preserveDraft ? previous.draftValue : this.formatProposalValue(proposal),
        };
      }),
    }));
  }

  private proposalErrorMessage(error: HttpErrorResponse): string {
    const detail = error.error?.detail;
    if (detail && typeof detail === 'object' && typeof detail.message === 'string') {
      return detail.message;
    }
    if (typeof detail === 'string') return detail;
    return 'The proposed value is not valid. Review it and try again.';
  }

  private mergeSources(sources: OnboardingSource[]): void {
    const merged = new Map(this.sources.map((source) => [source.id, source]));
    for (const source of this.prepareSources(sources)) merged.set(source.id, source);
    this.sources = Array.from(merged.values());
    for (const source of this.sources) {
      if (this.hasPendingProposals(source)) this.expandedSourceIds.add(source.id);
    }
  }

  private syncState(
    scrollMode: OnboardingScrollMode = 'none',
    anchor: ReviewScrollAnchor | null = null,
  ): void {
    const shouldScrollToBottom = scrollMode === 'bottom'
      || (scrollMode === 'auto' && isNearScrollBottom(this.chatScroll?.nativeElement));
    this.onboarding.getState().subscribe({
      next: (state) => {
        this.initialState = 'ready';
        this.applyState(state);
        if (scrollMode === 'preserve') this.restoreProposalAnchor(anchor);
        else if (shouldScrollToBottom) this.scrollToBottom();
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
    this.loadCompanyMedia();
    for (const source of this.sources) {
      if (this.hasPendingProposals(source)) this.expandedSourceIds.add(source.id);
    }
    const previousStage = this.currentStage;
    this.nextQuestion = state.next_question;
    this.currentStage = state.stage;
    this.team = state.team || EMPTY_TEAM_ONBOARDING;
    this.teamProjects = this.team.projects || [];
    this.initializePublicPresence(state.profile.data);
    this.isCompleted = state.profile.completion.can_complete;
    this.showWelcome = state.stage === 'website';
    if (this.pollingTimer) clearTimeout(this.pollingTimer);
    if (state.stage === 'processing') this.schedulePolling();
    else this.pollingStartedAt = 0;
    this.cdr.detectChanges();
    if (previousStage !== state.stage && ['logo_review', 'team', 'enrichment'].includes(state.stage)) {
      this.scrollToBottom();
    }
  }

  private applyTurn(turn: ChatTurnResponse): void {
    const wasCompleted = this.isCompleted;
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
    this.syncState('none');
    if (!wasCompleted && this.isCompleted) this.router.navigateByUrl('/app/company');
  }

  private refreshTeam(syncStage = false): void {
    this.onboarding.getTeam().subscribe({
      next: team => {
        this.team = team;
        this.teamProjects = team.projects || [];
        if (syncStage) this.syncState('bottom');
        this.cdr.detectChanges();
      },
      error: () => { this.teamError = 'The team status could not be refreshed.'; },
    });
  }

  private initializePublicPresence(data: Record<string, unknown>): void {
    const values = (key: string): string => Array.isArray(data[key])
      ? (data[key] as unknown[]).map(String).join(', ')
      : (typeof data[key] === 'string' ? String(data[key]) : '');
    if (!this.publicPresenceDirty.has('public_contact_emails')) this.publicEmails = values('public_contact_emails');
    if (!this.publicPresenceDirty.has('public_contact_phones')) this.publicPhones = values('public_contact_phones');
    if (!this.publicPresenceDirty.has('corporate_social_profiles')) this.socialProfiles = values('corporate_social_profiles');
  }

  publicPresenceStatus(field: string): ValidationStatus {
    return this.profile.fields.find(item => item.key === field)?.status || 'missing';
  }

  isPublicPresenceResolved(field: string): boolean {
    return ['confirmed', 'corrected_by_user'].includes(this.publicPresenceStatus(field));
  }

  shouldEditPublicPresence(field: string): boolean {
    return !this.isPublicPresenceResolved(field) || this.publicPresenceEditing.has(field);
  }

  editPublicPresence(field: string): void {
    this.publicPresenceEditing.add(field);
    this.publicPresenceDirty.add(field);
  }

  markPublicPresenceDirty(field: string): void {
    this.publicPresenceDirty.add(field);
    this.publicPresenceSaved = false;
  }

  get editablePublicPresenceFields(): string[] {
    return ['public_contact_emails', 'public_contact_phones', 'corporate_social_profiles']
      .filter(field => this.shouldEditPublicPresence(field));
  }

  get publicPresenceResolvedCount(): number {
    return ['public_contact_emails', 'public_contact_phones', 'corporate_social_profiles']
      .filter(field => this.isPublicPresenceResolved(field)).length;
  }

  private splitList(value: string): string[] {
    return Array.from(new Set(value.split(/[\n,;]/).map(item => item.trim()).filter(Boolean)));
  }

  private schedulePolling(): void {
    if (this.pollingTimer) clearTimeout(this.pollingTimer);
    if (!this.pollingStartedAt) this.pollingStartedAt = Date.now();
    const delay = Date.now() - this.pollingStartedAt > 30_000 ? 5000 : 2000;
    this.pollingTimer = setTimeout(() => this.syncState('auto'), delay);
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

  private activeQuestionMessageId(): string | null {
    const active = [...this.visibleMessages].reverse().find((message) =>
      message.sender === 'ai'
      && this.hasQuestionPayload(message)
      && !message.response_payload
      && !!message.id
    );
    return active?.id || null;
  }

  private updateProposal(sourceId: string, proposalId: string, patch: Partial<SourceProposal>): void {
    this.sources = this.sources.map((source) => source.id !== sourceId ? source : ({
      ...source,
      proposals: source.proposals.map((item) => item.id === proposalId ? { ...item, ...patch } : item),
    }));
    this.cdr.detectChanges();
  }

  private restoreProposalAnchor(anchor: ReviewScrollAnchor | null): void {
    if (!anchor) return;
    setTimeout(() => {
      restoreReviewScrollAnchor(this.chatScroll?.nativeElement, anchor);
      this.cdr.detectChanges();
    });
  }
  private restoreProposalContext(anchor: ReviewScrollAnchor | null, focusProposalId: string | null): void {
    setTimeout(() => {
      const container = this.chatScroll?.nativeElement;
      restoreReviewScrollAnchor(container, anchor);
      if (container && focusProposalId) {
        const proposal = Array.from(container.querySelectorAll<HTMLElement>('[data-proposal-id]'))
          .find(element => element.dataset['proposalId'] === focusProposalId);
        proposal?.querySelector<HTMLElement>('input, textarea, button:not([disabled])')?.focus({ preventScroll: true });
      }
      this.cdr.detectChanges();
    });
  }

  private scrollToBottom(): void {
    setTimeout(() => {
      const element = this.chatScroll?.nativeElement;
      if (element) element.scrollTop = element.scrollHeight;
    }, 100);
  }
}
