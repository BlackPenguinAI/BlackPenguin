import { ChangeDetectorRef, Component, ElementRef, OnDestroy, OnInit, ViewChild } from '@angular/core';
import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterModule } from '@angular/router';
import { marked } from 'marked';
import { Subscription } from 'rxjs';

import { SpeechRecognitionService } from '../../../../core/services/speech-recognition.service';

import {
  Campaign, ChatAttachment, ChatMessage, EMPTY_PROJECT_PROFILE, MetaConnection, ProjectFieldProgress,
  ProjectProfile, ProjectSource, SourceProposal, ValidationStatus,
} from './project-onboarding.models';
import { ProjectOnboardingService } from './project-onboarding.service';

@Component({
  selector: 'app-project-chat', standalone: true,
  imports: [CommonModule, FormsModule, RouterModule],
  templateUrl: './project-chat.html', styleUrls: ['./project-chat.scss'],
})
export class ProjectChatComponent implements OnInit, OnDestroy {
  @ViewChild('chatScroll') chatScroll!: ElementRef<HTMLElement>;
  projectId = '';
  prompt = '';
  userName = '';
  isAnalyzing = false;
  isUploading = false;
  isRecording = false;
  readonly speechSupported: boolean;
  selectedFiles: File[] = [];
  errorMessage = '';
  messages: ChatMessage[] = [];
  sources: ProjectSource[] = [];
  campaigns: Campaign[] = [];
  metaConnections: MetaConnection[] = [];
  profile: ProjectProfile = EMPTY_PROJECT_PROFILE;
  showCampaignForm = false;
  showMetaForm = false;
  newCampaign: Partial<Campaign> = { name: '', platform: 'meta', status: 'draft' };
  metaForm = { label: '', access_token: '', business_account_id: '', ad_account_id: '', page_id: '' };
  private readonly markdownCache = new Map<string, string>();
  private readonly speechSubscriptions = new Subscription();
  private speechBase = '';

  constructor(
    private readonly route: ActivatedRoute,
    private readonly onboarding: ProjectOnboardingService,
    private readonly cdr: ChangeDetectorRef,
    private readonly speech: SpeechRecognitionService,
  ) { this.speechSupported = speech.isSupported; }

  ngOnInit(): void {
    this.projectId = this.route.snapshot.paramMap.get('id') || '';
    this.userName = localStorage.getItem('bp_name') || 'User';
    this.loadProfile(); this.loadHistory(); this.loadSources(); this.loadCampaigns(); this.loadMetaConnections();
    this.speechSubscriptions.add(this.speech.state$.subscribe((state) => {
      this.isRecording = state === 'listening';
      this.cdr.detectChanges();
    }));
    this.speechSubscriptions.add(this.speech.transcript$.subscribe(({ finalText, interimText }) => {
      this.prompt = this.joinSpeech(this.speechBase, finalText, interimText);
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
  }

  get canSend(): boolean { return (!!this.prompt.trim() || !!this.selectedFiles.length) && !this.isAnalyzing && !this.profile.completion.can_complete; }
  get nextBlocker(): string { return this.profile.completion.blockers[0]?.label || 'Final profile approval'; }
  fieldsForSection(section: string): ProjectFieldProgress[] { return this.profile.fields.filter((field) => field.section === section); }

  loadProfile(): void {
    this.onboarding.getProfile(this.projectId).subscribe({
      next: (profile) => this.profile = profile,
      error: (error: HttpErrorResponse) => { if (error.status !== 401) this.errorMessage = 'The Project Profile could not be loaded.'; },
    });
  }
  loadHistory(): void {
    this.onboarding.getHistory(this.projectId).subscribe({
      next: (messages) => { this.messages = messages; messages.length ? this.scrollToBottom() : this.startConversation(); },
      error: (error: HttpErrorResponse) => { if (error.status !== 401) this.errorMessage = 'The project conversation could not be loaded.'; },
    });
  }
  loadSources(): void { this.onboarding.getSources(this.projectId).subscribe({ next: (items) => this.sources = this.prepareSources(items) }); }
  loadCampaigns(): void { this.onboarding.getCampaigns(this.projectId).subscribe({ next: (items) => this.campaigns = items }); }
  loadMetaConnections(): void { this.onboarding.getMetaConnections().subscribe({ next: (items) => this.metaConnections = items }); }

  startConversation(): void {
    this.isAnalyzing = true;
    this.onboarding.startChat(this.projectId).subscribe({
      next: (turn) => { this.messages.push(turn.message); this.profile = turn.profile; this.isAnalyzing = false; this.scrollToBottom(); },
      error: () => { this.isAnalyzing = false; this.errorMessage = 'The Project Assistant could not start.'; },
    });
  }
  handleKeyDown(event: KeyboardEvent): void { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); if (this.canSend) this.sendMessage(); } }
  sendMessage(): void {
    if (!this.canSend) return;
    if (this.isRecording) this.speech.stop();
    const content = this.prompt.trim();
    const files = [...this.selectedFiles];
    const optimistic: ChatMessage = {
      sender: 'user',
      content: content || `Attached ${files.length} project file${files.length === 1 ? '' : 's'}.`,
      created_at: new Date(),
      attachments: files.map((file, index) => ({
        id: `pending-${index}`, kind: 'uploaded_file', name: file.name,
        mime_type: file.type || null, size_bytes: file.size, status: 'processing',
        url: null, download_url: null,
      })),
    };
    this.prompt = ''; this.selectedFiles = []; this.errorMessage = '';
    this.messages.push(optimistic); this.isAnalyzing = true; this.isUploading = !!files.length; this.scrollToBottom();
    const request = files.length
      ? this.onboarding.sendMessageWithFiles(this.projectId, content, files)
      : this.onboarding.sendMessage(this.projectId, content);
    request.subscribe({
      next: (turn) => {
        if (turn.user_message) Object.assign(optimistic, turn.user_message);
        this.messages.push(turn.message); this.profile = turn.profile; this.mergeSources(turn.sources);
        this.isAnalyzing = false; this.isUploading = false; this.scrollToBottom();
      },
      error: () => {
        this.messages = this.messages.filter((message) => message !== optimistic);
        this.prompt = content; this.selectedFiles = files;
        this.isAnalyzing = false; this.isUploading = false;
        this.errorMessage = 'The message could not be processed. Your text and selected files were restored.';
        this.cdr.detectChanges();
      },
    });
  }

  onFilesSelected(event: Event): void {
    const input = event.target as HTMLInputElement; const files = Array.from(input.files || []); input.value = '';
    if (!files.length || this.isUploading) return;
    const remaining = Math.max(0, 10 - this.selectedFiles.length);
    this.selectedFiles = [...this.selectedFiles, ...files.slice(0, remaining)];
    if (files.length > remaining) this.errorMessage = 'A maximum of 10 files can be attached to one message.';
  }
  removeSelectedFile(index: number): void { this.selectedFiles = this.selectedFiles.filter((_, itemIndex) => itemIndex !== index); }

  toggleRecording(): void {
    if (!this.speechSupported || this.isAnalyzing || this.profile.completion.can_complete) return;
    if (this.isRecording) {
      this.speech.stop();
      return;
    }
    this.errorMessage = '';
    this.speechBase = this.prompt.trim();
    this.speech.start((localStorage.getItem('bp_lang') || 'en') === 'es' ? 'es-PE' : 'en-US');
  }

  downloadAttachment(attachment: ChatAttachment): void {
    if (!attachment.download_url) return;
    this.onboarding.downloadAttachment(attachment.download_url).subscribe({
      next: (blob) => {
        const url = URL.createObjectURL(blob);
        const anchor = document.createElement('a');
        anchor.href = url; anchor.download = attachment.name; anchor.click();
        URL.revokeObjectURL(url);
      },
      error: () => this.errorMessage = 'The attached file could not be downloaded.',
    });
  }

  formatBytes(bytes: number | null): string {
    if (bytes == null) return '';
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }
  decideProposal(source: ProjectSource, proposal: SourceProposal, action: 'confirm' | 'correct' | 'reject'): void {
    const value = action === 'correct' ? this.parseValue(proposal.draftValue || '') : undefined;
    this.onboarding.decideProposal(this.projectId, proposal.id, action, value).subscribe({
      next: (result) => { const index = source.proposals.findIndex((item) => item.id === proposal.id); if (index >= 0) source.proposals[index] = { ...result.proposal, draftValue: this.formatValue(result.proposal.value) }; this.profile = result.profile; },
      error: () => this.errorMessage = 'That proposal could not be updated.',
    });
  }

  createCampaign(): void {
    if (!this.newCampaign.name?.trim()) return;
    this.onboarding.createCampaign(this.projectId, this.newCampaign).subscribe({
      next: (campaign) => { this.campaigns.push(campaign); this.newCampaign = { name: '', platform: 'meta', status: 'draft' }; this.showCampaignForm = false; },
      error: () => this.errorMessage = 'The campaign could not be created.',
    });
  }
  createMetaConnection(): void {
    if (!this.metaForm.label || !this.metaForm.access_token) return;
    this.onboarding.createMetaConnection(this.metaForm).subscribe({
      next: (connection) => { this.metaConnections.push(connection); this.metaForm = { label: '', access_token: '', business_account_id: '', ad_account_id: '', page_id: '' }; this.showMetaForm = false; },
      error: () => this.errorMessage = 'The Meta connection could not be stored.',
    });
  }
  verifyMeta(connection: MetaConnection): void {
    this.onboarding.verifyMetaConnection(connection.id).subscribe({
      next: (verified) => { const index = this.metaConnections.findIndex((item) => item.id === verified.id); if (index >= 0) this.metaConnections[index] = verified; },
      error: () => this.errorMessage = 'Meta could not verify that connection.',
    });
  }

  renderMarkdown(content: string): string { const cached = this.markdownCache.get(content); if (cached) return cached; const rendered = marked.parse(content, { async: false, breaks: true }) as string; this.markdownCache.set(content, rendered); return rendered; }
  statusIcon(status: ValidationStatus): string { return ({ confirmed: 'check_circle', corrected_by_user: 'check_circle', not_applicable: 'remove_circle', conflicting: 'error', stale: 'history', expired: 'event_busy', pending_confirmation: 'schedule', extracted: 'manage_search', missing: 'radio_button_unchecked' })[status]; }
  statusClass(status: ValidationStatus): string { if (status === 'confirmed' || status === 'corrected_by_user') return 'text-green-400'; if (status === 'conflicting' || status === 'expired') return 'text-red-400'; if (status === 'stale' || status === 'pending_confirmation' || status === 'extracted') return 'text-secondary'; return 'text-gray-600'; }
  statusLabel(status: ValidationStatus): string { return status.replaceAll('_', ' '); }
  formatValue(value: unknown): string { return typeof value === 'string' ? value : value == null ? '' : JSON.stringify(value); }
  trackSource(_: number, item: ProjectSource): string { return item.id; }
  trackField(_: number, item: ProjectFieldProgress): string { return item.key; }

  private parseValue(value: string): unknown { const trimmed = value.trim(); try { return /^[\[{]/.test(trimmed) ? JSON.parse(trimmed) : trimmed; } catch { return trimmed; } }
  private joinSpeech(base: string, finalText: string, interimText: string): string {
    return [base, finalText, interimText].filter(Boolean).join(' ').replace(/\s+/g, ' ').trimStart();
  }
  private prepareSources(items: ProjectSource[]): ProjectSource[] { return items.map((source) => ({ ...source, proposals: source.proposals.map((proposal) => ({ ...proposal, draftValue: this.formatValue(proposal.value) })) })); }
  private mergeSources(items: ProjectSource[]): void { for (const source of this.prepareSources(items)) { const index = this.sources.findIndex((item) => item.id === source.id); index >= 0 ? this.sources[index] = source : this.sources.unshift(source); } }
  private scrollToBottom(): void { setTimeout(() => { const element = this.chatScroll?.nativeElement; if (element) element.scrollTop = element.scrollHeight; this.cdr.detectChanges(); }, 100); }
}
