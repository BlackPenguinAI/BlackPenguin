import { ChangeDetectorRef, Component, ElementRef, OnInit, ViewChild } from '@angular/core';
import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterModule } from '@angular/router';
import { marked } from 'marked';

import {
  Campaign, ChatMessage, EMPTY_PROJECT_PROFILE, MetaConnection, ProjectFieldProgress,
  ProjectProfile, ProjectSource, SourceProposal, ValidationStatus,
} from './project-onboarding.models';
import { ProjectOnboardingService } from './project-onboarding.service';

@Component({
  selector: 'app-project-chat', standalone: true,
  imports: [CommonModule, FormsModule, RouterModule],
  templateUrl: './project-chat.html', styleUrls: ['./project-chat.scss'],
})
export class ProjectChatComponent implements OnInit {
  @ViewChild('chatScroll') chatScroll!: ElementRef<HTMLElement>;
  projectId = '';
  prompt = '';
  userName = '';
  isAnalyzing = false;
  isUploading = false;
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

  constructor(
    private readonly route: ActivatedRoute,
    private readonly onboarding: ProjectOnboardingService,
    private readonly cdr: ChangeDetectorRef,
  ) {}

  ngOnInit(): void {
    this.projectId = this.route.snapshot.paramMap.get('id') || '';
    this.userName = localStorage.getItem('bp_name') || 'User';
    this.loadProfile(); this.loadHistory(); this.loadSources(); this.loadCampaigns(); this.loadMetaConnections();
  }

  get canSend(): boolean { return !!this.prompt.trim() && !this.isAnalyzing && !this.profile.completion.can_complete; }
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
    const content = this.prompt.trim(); this.prompt = ''; this.errorMessage = '';
    this.messages.push({ sender: 'user', content, created_at: new Date() }); this.isAnalyzing = true; this.scrollToBottom();
    this.onboarding.sendMessage(this.projectId, content).subscribe({
      next: (turn) => { this.messages.push(turn.message); this.profile = turn.profile; this.mergeSources(turn.sources); this.isAnalyzing = false; this.scrollToBottom(); },
      error: () => { this.isAnalyzing = false; this.errorMessage = 'The message could not be processed. The profile was not changed.'; },
    });
  }

  onFilesSelected(event: Event): void {
    const input = event.target as HTMLInputElement; const files = Array.from(input.files || []); input.value = '';
    if (!files.length || this.isUploading) return;
    this.isUploading = true; this.errorMessage = '';
    this.onboarding.uploadFiles(this.projectId, files).subscribe({
      next: (sources) => { this.mergeSources(sources); this.isUploading = false; this.messages.push({ sender: 'ai', content: `**Source review ready:** ${sources.filter((s) => s.status === 'ready').length} of ${sources.length} files were processed. Review the proposed details below.`, created_at: new Date() }); this.scrollToBottom(); },
      error: () => { this.isUploading = false; this.errorMessage = 'Files could not be processed. Use PDF, DOCX, TXT, CSV, XLSX, JPG, PNG, or WEBP up to 15 MB.'; },
    });
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
  private prepareSources(items: ProjectSource[]): ProjectSource[] { return items.map((source) => ({ ...source, proposals: source.proposals.map((proposal) => ({ ...proposal, draftValue: this.formatValue(proposal.value) })) })); }
  private mergeSources(items: ProjectSource[]): void { for (const source of this.prepareSources(items)) { const index = this.sources.findIndex((item) => item.id === source.id); index >= 0 ? this.sources[index] = source : this.sources.unshift(source); } }
  private scrollToBottom(): void { setTimeout(() => { const element = this.chatScroll?.nativeElement; if (element) element.scrollTop = element.scrollHeight; this.cdr.detectChanges(); }, 100); }
}
