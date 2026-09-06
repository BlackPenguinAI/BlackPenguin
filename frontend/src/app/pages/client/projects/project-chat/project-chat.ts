import { ChangeDetectorRef, Component, ElementRef, OnDestroy, OnInit, ViewChild } from '@angular/core';
import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterModule } from '@angular/router';
import { marked } from 'marked';
import { catchError, finalize, of, Subscription, switchMap, timeout } from 'rxjs';

import { SpeechRecognitionService } from '../../../../core/services/speech-recognition.service';
import { OnboardingQuestion } from '../../../../shared/ui/onboarding-response-options/onboarding-response-options';
import { OnboardingAiMessageComponent } from '../../../../shared/ui/onboarding-ai-message/onboarding-ai-message';
import { OnboardingWelcomeComponent } from '../../../../shared/ui/onboarding-welcome/onboarding-welcome';
import {
  captureReviewScrollAnchor,
  isNearScrollBottom,
  OnboardingScrollMode,
  restoreReviewScrollAnchor,
  ReviewScrollAnchor,
} from '../../../../shared/utils/review-scroll-anchor';

import {
  Campaign, ChatAttachment, ChatMessage, ChatTurn, EMPTY_PROJECT_PROFILE, MetaConnection,
  MetaSetupConfiguration, OnboardingState, ProjectAssignment, ProjectFieldProgress, ProjectProfile,
  ProjectSalesCandidate, ProjectSource, SectionProgress, SourceProposal, ValidationStatus,
  ProjectPropertyType, PropertyTypeCatalog,
} from './project-onboarding.models';
import { ProjectOnboardingService } from './project-onboarding.service';
import {
  errorCount,
  FormErrors,
  validateMetaSetup,
  validatePropertyType,
  validateProposalDraft,
  validateSalesInvite,
  toPropertyTypePayload,
} from './project-form-validation';

@Component({
  selector: 'app-project-chat', standalone: true,
  imports: [CommonModule, FormsModule, RouterModule, OnboardingAiMessageComponent, OnboardingWelcomeComponent],
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
  isCompleting = false;
  readonly speechSupported: boolean;
  selectedFiles: File[] = [];
  errorMessage = '';
  messages: ChatMessage[] = [];
  sources: ProjectSource[] = [];
  campaigns: Campaign[] = [];
  metaConnections: MetaConnection[] = [];
  companyUsers: ProjectSalesCandidate[] = [];
  projectTeam: ProjectAssignment[] = [];
  selectedSalesUserId = '';
  salesInvite = { first_name: '', last_name: '', email: '' };
  teamBusy = false;
  teamSetupMessage = '';
  authorizationBusy = false;
  metaSetupConfig: MetaSetupConfiguration = { partner_business_manager_id: null, configured: false };
  metaSetup = {
    meta_connection_id: '', page_id: '', ad_account_id: '', lead_form_id: '',
    campaign_name: 'Meta Lead Ads', external_campaign_id: '', external_adset_id: '',
    external_ad_id: '', instagram_account_id: '',
    page_access_confirmed: false, ad_account_access_confirmed: false, leads_access_confirmed: false,
  };
  metaSetupBusy = false;
  metaSetupMessage = '';
  propertyCatalog: PropertyTypeCatalog = { items: [], confirmed_count: 0, candidate_count: 0, limit: 0, remaining: 0, catalog_complete: false };
  readonly savingPropertyTypeIds = new Set<string>();
  readonly removingPropertyTypeIds = new Set<string>();
  readonly propertyTypeServerErrors = new Map<string, FormErrors>();
  readonly dirtyPropertyTypeIds = new Set<string>();
  creatingPropertyType = false;
  confirmingPropertyCatalog = false;
  coverBusy = false;
  coverUploadBusy = false;
  selectedCoverSourceId: string | null = null;
  showPropertyTypeForm = false;
  propertyTypeDraft: Partial<ProjectPropertyType> = this.emptyPropertyType();
  readonly propertyTypeDraftImageSelection = new Set<string>();
  readonly propertyTypeImageSelection = new Map<string, Set<string>>();
  readonly areaUnits = ['m²', 'ft²', 'ha', 'acres'];
  readonly currencies = [
    { code: 'USD', name: 'US Dollar' }, { code: 'PEN', name: 'Peruvian Sol' },
    { code: 'EUR', name: 'Euro' }, { code: 'MXN', name: 'Mexican Peso' },
    { code: 'COP', name: 'Colombian Peso' }, { code: 'BRL', name: 'Brazilian Real' },
    { code: 'CLP', name: 'Chilean Peso' }, { code: 'ARS', name: 'Argentine Peso' },
    { code: 'CAD', name: 'Canadian Dollar' }, { code: 'GBP', name: 'Pound Sterling' },
  ];
  readonly sourceImageUrls = new Map<string, string>();
  profile: ProjectProfile = EMPTY_PROJECT_PROFILE;
  showWelcome = false;
  initialState: 'loading' | 'ready' | 'error' = 'loading';
  nextQuestion: OnboardingQuestion | null = null;
  showCampaignForm = false;
  showMetaForm = false;
  newCampaign: Partial<Campaign> = { name: '', platform: 'meta', status: 'draft' };
  metaForm = { label: '', access_token: '', business_account_id: '', ad_account_id: '', page_id: '' };
  private readonly markdownCache = new Map<string, string>();
  private readonly speechSubscriptions = new Subscription();
  private speechBase = '';
  private pollingTimer?: ReturnType<typeof setTimeout>;
  private replyToMessageId: string | null = null;
  private retryClientMessageId: string | null = null;
  private lastStateVersion = 0;
  private pollingStartedAt = 0;
  private propertyCatalogRequestVersion = 0;
  private readonly expandedSourceIds = new Set<string>();
  private readonly activationFieldKeys = new Set([
    'sales_authorization', 'sales_contacts', 'appointment_routing', 'campaigns_defined', 'meta_connection_verified',
  ]);

  constructor(
    private readonly route: ActivatedRoute,
    private readonly onboarding: ProjectOnboardingService,
    private readonly cdr: ChangeDetectorRef,
    private readonly speech: SpeechRecognitionService,
    private readonly router: Router,
  ) { this.speechSupported = speech.isSupported; }

  ngOnInit(): void {
    this.projectId = this.route.snapshot.paramMap.get('id') || '';
    this.userName = localStorage.getItem('bp_name') || 'User';
    this.syncState(); this.loadCampaigns(); this.loadMetaConnections(); this.loadSalesTeam(); this.loadMetaSetupConfiguration();
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
    if (this.pollingTimer) clearTimeout(this.pollingTimer);
    for (const url of this.sourceImageUrls.values()) URL.revokeObjectURL(url);
  }

  get canSend(): boolean { return (!!this.prompt.trim() || !!this.selectedFiles.length) && !this.isAnalyzing && !this.hasPendingReview; }
  get projectName(): string { return this.profile.project_name || 'Untitled Project'; }
  get hasProcessingSources(): boolean { return this.sources.some((source) => source.status === 'processing'); }
  get nextBlocker(): string { return this.profile.completion.blockers[0]?.label || 'Final profile approval'; }
  get profileSections(): SectionProgress[] {
    return this.profile.completion.sections
      .filter((section) => !['routing', 'campaigns'].includes(section.key))
      .map((section) => {
        const fields = this.fieldsForSection(section.key);
        const completed = fields.filter((field) => this.isResolvedStatus(field.status)).length;
        return {
          ...section,
          completed,
          total: fields.length,
          percentage: fields.length ? Math.round(100 * completed / fields.length) : 100,
        };
      })
      .filter((section) => section.total > 0);
  }
  fieldsForSection(section: string): ProjectFieldProgress[] {
    return this.profile.fields.filter((field) => field.section === section && !this.activationFieldKeys.has(field.key));
  }
  get projectProfileProgress(): { completed: number; total: number; percentage: number } {
    const fields = this.profile.fields.filter((field) => !this.activationFieldKeys.has(field.key));
    const completed = fields.filter((field) => this.isResolvedStatus(field.status)).length;
    return { completed, total: fields.length, percentage: fields.length ? Math.round(100 * completed / fields.length) : 0 };
  }
  get aiAuthorizationStatus(): ValidationStatus {
    return this.profile.fields.find((field) => field.key === 'sales_authorization')?.status || 'missing';
  }
  get metaActivationLabel(): string {
    if (this.metaConnections.some((item) => item.verification_status === 'succeeded')) return 'Test completed';
    return this.profile.fields.find((field) => field.key === 'campaigns_defined')?.status === 'deferred'
      ? 'Configure later'
      : 'Pending';
  }

  propertyTypeErrors(item: Partial<ProjectPropertyType>): FormErrors {
    return { ...validatePropertyType(item), ...(item.id ? this.propertyTypeServerErrors.get(item.id) : {}) };
  }
  propertyTypeError(item: Partial<ProjectPropertyType>, field: string): string { return this.propertyTypeErrors(item)[field] || ''; }
  propertyTypeFormError(item: Partial<ProjectPropertyType>): string { return this.propertyTypeErrors(item)['_form'] || ''; }
  propertyTypeErrorCount(item: Partial<ProjectPropertyType>): number {
    const errors = { ...this.propertyTypeErrors(item) };
    delete errors['_form'];
    return errorCount(errors);
  }
  canSavePropertyType(item: Partial<ProjectPropertyType>): boolean {
    return !this.isPropertyTypeSaving(item)
      && !this.propertyTypeFormError(item)
      && this.propertyTypeErrorCount(item) === 0;
  }
  isPropertyTypeSaving(item: Partial<ProjectPropertyType>): boolean {
    return item.id ? this.savingPropertyTypeIds.has(item.id) : this.creatingPropertyType;
  }
  get catalogReady(): boolean {
    return !this.creatingPropertyType
      && this.savingPropertyTypeIds.size === 0
      && !this.confirmingPropertyCatalog
      && this.propertyCatalog.confirmed_count > 0
      && this.propertyCatalog.candidate_count === 0
      && this.propertyCatalog.items
        .filter(item => item.review_status === 'confirmed')
        .every(item => this.propertyTypeErrorCount(item) === 0);
  }
  get salesInviteErrors(): FormErrors { return validateSalesInvite(this.salesInvite); }
  get salesInviteErrorCount(): number { return errorCount(this.salesInviteErrors); }
  get canInviteSalesUser(): boolean { return !this.teamBusy && this.salesInviteErrorCount === 0; }
  get metaSetupErrors(): FormErrors { return validateMetaSetup(this.metaSetup); }
  get metaSetupErrorCount(): number { return errorCount(this.metaSetupErrors); }
  get canTestMetaSetup(): boolean {
    return !this.metaSetupBusy && this.metaSetupConfig.configured && this.metaSetupErrorCount === 0;
  }

  loadProfile(): void {
    this.onboarding.getProfile(this.projectId).subscribe({
      next: (profile) => this.profile = profile,
      error: (error: HttpErrorResponse) => { if (error.status !== 401) this.errorMessage = 'The Project Profile could not be loaded.'; },
    });
  }
  loadHistory(): void {
    this.onboarding.getHistory(this.projectId).subscribe({
      next: (messages) => {
        this.messages = messages; this.showWelcome = messages.length === 0;
        if (messages.length) this.scrollToBottom();
      },
      error: (error: HttpErrorResponse) => { if (error.status !== 401) this.errorMessage = 'The project conversation could not be loaded.'; },
    });
  }
  loadSources(): void { this.onboarding.getSources(this.projectId).subscribe({ next: (items) => { this.sources = this.prepareSources(items); this.loadSourceImagePreviews(); } }); }
  loadCampaigns(): void { this.onboarding.getCampaigns(this.projectId).subscribe({ next: (items) => this.campaigns = items }); }
  loadMetaConnections(): void { this.onboarding.getMetaConnections().subscribe({ next: (items) => this.metaConnections = items }); }
  selectMetaConnection(): void {
    const connection = this.metaConnections.find(item => item.id === this.metaSetup.meta_connection_id);
    if (!connection) return;
    this.metaSetup.page_id = connection.page_id || '';
    this.metaSetup.ad_account_id = connection.ad_account_id || '';
    this.metaSetup.instagram_account_id = connection.instagram_account_id || '';
  }
  loadSalesTeam(): void {
    this.onboarding.getProjectTeam(this.projectId).subscribe({ next: (items) => this.projectTeam = items });
    this.onboarding.getSalesCandidates(this.projectId).subscribe({
      next: (items) => this.companyUsers = items,
      error: () => this.errorMessage = 'Company Sales users could not be loaded.',
    });
  }
  loadMetaSetupConfiguration(): void {
    this.onboarding.getMetaSetupConfiguration(this.projectId).subscribe({
      next: (configuration) => this.metaSetupConfig = configuration,
    });
  }
  loadPropertyTypes(): void {
    const requestVersion = ++this.propertyCatalogRequestVersion;
    this.onboarding.getPropertyTypes(this.projectId).subscribe({
      next: catalog => {
        if (requestVersion !== this.propertyCatalogRequestVersion) return;
        const localItems = new Map(this.propertyCatalog.items.map(item => [item.id, item]));
        this.propertyCatalog = {
          ...catalog,
          items: catalog.items.map(item => {
            const local = localItems.get(item.id);
            if (local && (this.dirtyPropertyTypeIds.has(item.id) || this.savingPropertyTypeIds.has(item.id))) return local;
            return this.normalizePropertyType(item);
          }),
        };
        this.cdr.detectChanges();
      },
      error: () => { this.errorMessage = 'The property type catalog could not be loaded.'; },
    });
  }

  saveNewPropertyType(): void {
    if (!this.canSavePropertyType(this.propertyTypeDraft)) return;
    this.creatingPropertyType = true;
    this.errorMessage = '';
    const selectedImageIds = [...this.propertyTypeDraftImageSelection];
    this.onboarding.createPropertyType(this.projectId, toPropertyTypePayload(this.propertyTypeDraft)).pipe(
      timeout(20_000),
      switchMap(updated => {
        if (!selectedImageIds.length) return of(updated);
        return this.onboarding.attachPropertyTypeMedia(this.projectId, updated.id, selectedImageIds).pipe(
          catchError(() => {
            this.propertyTypeImageSelection.set(updated.id, new Set(selectedImageIds));
            this.errorMessage = 'The property type was saved, but its images could not be attached. The selection is ready to retry.';
            return of(updated);
          }),
        );
      }),
      finalize(() => { this.creatingPropertyType = false; this.cdr.detectChanges(); }),
    ).subscribe({
      next: updated => {
        this.propertyCatalog = {
          ...this.propertyCatalog,
          items: [...this.propertyCatalog.items, this.normalizePropertyType(updated)],
          confirmed_count: this.propertyCatalog.confirmed_count + 1,
          remaining: Math.max(0, this.propertyCatalog.remaining - 1),
        };
        this.showPropertyTypeForm = false;
        this.propertyTypeDraft = this.emptyPropertyType();
        this.propertyTypeDraftImageSelection.clear();
        this.syncState('none');
      },
      error: (error: HttpErrorResponse) => this.handlePropertyTypeError(null, error, 'The property type could not be saved.'),
    });
  }

  confirmPropertyType(item: ProjectPropertyType): void {
    if (!this.canSavePropertyType(item)) return;
    this.savingPropertyTypeIds.add(item.id);
    this.propertyTypeServerErrors.delete(item.id);
    this.errorMessage = '';
    this.onboarding.updatePropertyType(this.projectId, item.id, toPropertyTypePayload(item)).pipe(
      timeout(20_000),
      finalize(() => { this.savingPropertyTypeIds.delete(item.id); this.cdr.detectChanges(); }),
    ).subscribe({
      next: updated => {
        this.dirtyPropertyTypeIds.delete(item.id);
        this.propertyTypeServerErrors.delete(item.id);
        this.replacePropertyType(updated);
        this.syncState('none');
      },
      error: (error: HttpErrorResponse) => this.handlePropertyTypeError(
        item.id, error, 'This property type could not be saved. Review the highlighted fields and try again.',
      ),
    });
  }

  markPropertyTypeDirty(item: ProjectPropertyType): void {
    this.dirtyPropertyTypeIds.add(item.id);
    this.propertyTypeServerErrors.delete(item.id);
    this.errorMessage = '';
  }

  rejectPropertyType(item: ProjectPropertyType): void {
    if (this.removingPropertyTypeIds.has(item.id)) return;
    this.removingPropertyTypeIds.add(item.id);
    this.errorMessage = '';
    this.onboarding.deletePropertyType(this.projectId, item.id).pipe(
      timeout(20_000),
      finalize(() => { this.removingPropertyTypeIds.delete(item.id); this.cdr.detectChanges(); }),
    ).subscribe({
      next: () => {
        this.dirtyPropertyTypeIds.delete(item.id);
        this.propertyTypeServerErrors.delete(item.id);
        this.propertyCatalog = {
          ...this.propertyCatalog,
          items: this.propertyCatalog.items.filter(candidate => candidate.id !== item.id),
          candidate_count: Math.max(0, this.propertyCatalog.candidate_count - (item.review_status === 'candidate' ? 1 : 0)),
          confirmed_count: Math.max(0, this.propertyCatalog.confirmed_count - (item.review_status === 'confirmed' ? 1 : 0)),
        };
        this.syncState('none');
      },
      error: (error: HttpErrorResponse) => {
        this.errorMessage = this.apiDetail(error, 'This property type could not be removed. Refresh the catalog and try again.');
      },
    });
  }

  togglePropertyTypeImage(item: ProjectPropertyType, sourceId: string): void {
    const selected = this.propertyTypeImageSelection.get(item.id) || new Set<string>();
    selected.has(sourceId) ? selected.delete(sourceId) : selected.add(sourceId);
    this.propertyTypeImageSelection.set(item.id, selected);
  }

  toggleDraftPropertyTypeImage(sourceId: string): void {
    this.propertyTypeDraftImageSelection.has(sourceId)
      ? this.propertyTypeDraftImageSelection.delete(sourceId)
      : this.propertyTypeDraftImageSelection.add(sourceId);
  }

  attachSelectedImages(item: ProjectPropertyType): void {
    const selected = [...(this.propertyTypeImageSelection.get(item.id) || [])];
    if (!selected.length) return;
    this.onboarding.attachPropertyTypeMedia(this.projectId, item.id, selected).subscribe({
      next: updated => { this.propertyTypeImageSelection.delete(item.id); this.replacePropertyType(updated); },
      error: () => this.errorMessage = 'The selected images could not be attached to this property type.',
    });
  }

  deferPropertyTypeImages(item: ProjectPropertyType): void {
    this.onboarding.deferPropertyTypeImages(this.projectId, item.id).subscribe({ next: updated => this.replacePropertyType(updated) });
  }

  isPropertyTypeImageSelected(item: ProjectPropertyType, sourceId: string): boolean {
    return this.propertyTypeImageSelection.get(item.id)?.has(sourceId) || false;
  }

  get readyProjectImages(): ProjectSource[] { return this.sources.filter(source => source.kind === 'image' && source.status === 'ready' && !!source.download_url); }
  get showCoverPicker(): boolean { return this.nextQuestion?.input_type === 'project_cover'; }
  get showPropertyCatalog(): boolean { return this.nextQuestion?.input_type === 'property_type_catalog' || this.showPropertyTypeForm; }

  private emptyPropertyType(): Partial<ProjectPropertyType> {
    return { name: '', code: null, description: null, bedrooms: null, bathrooms: null, area_min: null, area_max: null,
      area_unit: 'm²', total_units: null, available_units: null, starting_price: null, maximum_price: null,
      currency: 'USD', features: [], inventory_updated_at: new Date().toISOString().slice(0, 10), images_status: 'pending', sort_order: 0 };
  }

  private replacePropertyType(updated: ProjectPropertyType): void {
    const normalized = this.normalizePropertyType(updated);
    const items = this.propertyCatalog.items.map(item => item.id === updated.id ? normalized : item);
    this.propertyCatalog = {
      ...this.propertyCatalog,
      items,
      confirmed_count: items.filter(item => item.review_status === 'confirmed').length,
      candidate_count: items.filter(item => item.review_status === 'candidate').length,
    };
    this.cdr.detectChanges();
  }

  private normalizePropertyType(item: ProjectPropertyType): ProjectPropertyType {
    return { ...item, inventory_updated_at: item.inventory_updated_at?.slice(0, 10) || null };
  }

  private handlePropertyTypeError(itemId: string | null, error: Error | HttpErrorResponse, fallback: string): void {
    const errors = this.propertyTypeApiErrors(error, fallback);
    if (itemId) this.propertyTypeServerErrors.set(itemId, errors);
    else this.errorMessage = errors['_form'] || Object.values(errors)[0] || fallback;
    this.cdr.detectChanges();
  }

  private propertyTypeApiErrors(error: Error | HttpErrorResponse, fallback: string): FormErrors {
    const httpError = error as HttpErrorResponse;
    if (error.name === 'TimeoutError' || httpError.status === 0) {
      return { _form: 'Saving took too long. Your changes remain in the form; check the connection and try again.' };
    }
    const detail = httpError.error?.detail;
    if (detail?.field_errors && typeof detail.field_errors === 'object') return detail.field_errors as FormErrors;
    if (Array.isArray(detail)) {
      const errors: FormErrors = {};
      for (const issue of detail) {
        const location = Array.isArray(issue?.loc) ? issue.loc : [];
        const candidate = String(location.at(-1) || '');
        const field = !candidate || candidate === 'body' ? '_form' : candidate;
        errors[field] = String(issue?.msg || fallback);
      }
      return Object.keys(errors).length ? errors : { _form: fallback };
    }
    if (typeof detail === 'string') return { _form: detail };
    if (typeof detail?.message === 'string') return { _form: detail.message };
    return { _form: fallback };
  }

  private apiDetail(error: HttpErrorResponse, fallback: string): string {
    const detail = error.error?.detail;
    return typeof detail === 'string' ? detail : detail?.message || fallback;
  }

  get availableSalesUsers(): ProjectSalesCandidate[] {
    const assigned = new Set(this.projectTeam.filter((item) => item.responsibility === 'sales').map((item) => item.user_id));
    return this.companyUsers.filter((item) => item.role === 'sales' && item.is_active && !assigned.has(item.id));
  }
  get assignedSalesUsers(): ProjectAssignment[] {
    return this.projectTeam.filter((item) => item.responsibility === 'sales' && item.is_active);
  }
  isStructuredQuestion(message: ChatMessage, inputType: string): boolean {
    return this.isActiveQuestion(message) && message.ui_payload?.input_type === inputType;
  }
  isGlobalStructuredQuestion(message: ChatMessage): boolean {
    return ['project_cover', 'property_type_catalog'].includes(message.ui_payload?.input_type || '');
  }
  hasPersistedStructuredTransition(message: ChatMessage): boolean {
    return message.sender === 'ai' && /^I saved\b/i.test(message.content.trim());
  }
  assignSelectedSalesUser(message: ChatMessage): void {
    if (!this.selectedSalesUserId || this.teamBusy) return;
    this.teamBusy = true; this.errorMessage = '';
    this.onboarding.assignSalesUser(this.projectId, this.selectedSalesUserId).subscribe({
      next: (assignment) => {
        this.projectTeam = [...this.projectTeam.filter((item) => item.user_id !== assignment.user_id), assignment];
        this.selectedSalesUserId = ''; this.teamBusy = false;
        this.teamSetupMessage = `${assignment.first_name || ''} ${assignment.last_name || ''}`.trim()
          + ' was assigned. Add another Sales user or continue with this team.';
      },
      error: (error: HttpErrorResponse) => {
        this.teamBusy = false;
        this.errorMessage = error.error?.detail || 'The Sales user could not be assigned.';
      },
    });
  }
  inviteSalesUser(message: ChatMessage): void {
    if (!this.canInviteSalesUser) return;
    this.teamBusy = true; this.errorMessage = '';
    this.onboarding.inviteAndAssignSalesUser(this.projectId, this.salesInvite).subscribe({
      next: (assignment) => {
        this.projectTeam = [...this.projectTeam, assignment];
        this.companyUsers = [...this.companyUsers, {
          id: assignment.user_id, email: assignment.email, first_name: assignment.first_name || undefined,
          last_name: assignment.last_name || undefined, role: 'sales', is_active: true,
        }];
        this.salesInvite = { first_name: '', last_name: '', email: '' }; this.teamBusy = false;
        this.teamSetupMessage = `${assignment.first_name || ''} ${assignment.last_name || ''}`.trim()
          + ' was created and assigned. Add another Sales user or continue with this team.';
      },
      error: (error: HttpErrorResponse) => {
        this.teamBusy = false;
        this.errorMessage = error.error?.detail || 'The Sales user could not be created and assigned.';
      },
    });
  }
  authorizeAiSales(message: ChatMessage): void {
    if (!message.id || this.authorizationBusy) return;
    this.authorizationBusy = true; this.errorMessage = '';
    this.onboarding.applyOnboardingAction(this.projectId, {
      action: 'authorize_ai_sales', question_message_id: message.id, client_action_id: this.createClientMessageId(),
    }).subscribe({
      next: (turn) => { this.authorizationBusy = false; this.applyTurn(turn); this.scrollToBottom(); },
      error: (error: HttpErrorResponse) => {
        this.authorizationBusy = false;
        this.handleStructuredActionError(error, 'The AI-assisted sales authorization could not be recorded.');
      },
    });
  }
  completeSalesTeam(message: ChatMessage): void { this.applySalesTeamDecision(message, 'complete_sales_team'); }
  deferSalesTeam(message: ChatMessage): void { this.applySalesTeamDecision(message, 'defer_sales_team'); }
  private applySalesTeamDecision(message: ChatMessage, action: 'complete_sales_team' | 'defer_sales_team'): void {
    if (!message.id || this.teamBusy) return;
    this.teamBusy = true; this.errorMessage = '';
    this.onboarding.applyOnboardingAction(this.projectId, {
      action, question_message_id: message.id, client_action_id: this.createClientMessageId(),
    }).subscribe({
      next: (turn) => { this.teamBusy = false; this.teamSetupMessage = ''; this.applyTurn(turn); this.scrollToBottom(); },
      error: (error: HttpErrorResponse) => {
        this.teamBusy = false;
        this.handleStructuredActionError(error, 'The Sales-team decision could not be saved.');
      },
    });
  }
  testMetaSetup(message: ChatMessage): void {
    if (!message.id || this.metaSetupBusy) return;
    if (!this.canTestMetaSetup) return;
    this.metaSetupBusy = true; this.metaSetupMessage = ''; this.errorMessage = '';
    const optional = (value: string) => value.trim() || undefined;
    this.onboarding.applyOnboardingAction(this.projectId, {
      action: 'complete_meta_setup', question_message_id: message.id, client_action_id: this.createClientMessageId(),
      ...this.metaSetup,
      meta_connection_id: optional(this.metaSetup.meta_connection_id),
      external_campaign_id: optional(this.metaSetup.external_campaign_id),
      external_adset_id: optional(this.metaSetup.external_adset_id),
      external_ad_id: optional(this.metaSetup.external_ad_id),
      instagram_account_id: optional(this.metaSetup.instagram_account_id),
    }).subscribe({
      next: (turn) => {
        this.metaSetupBusy = false;
        this.metaSetupMessage = 'Simulated connection successful. Live Meta access must still be verified before activation.';
        this.applyTurn(turn); this.loadCampaigns(); this.loadMetaConnections(); this.scrollToBottom();
      },
      error: (error: HttpErrorResponse) => {
        this.metaSetupBusy = false;
        this.handleStructuredActionError(error, 'The simulated Meta connection test could not be completed.');
      },
    });
  }
  deferMetaSetup(message: ChatMessage): void {
    if (!message.id || this.metaSetupBusy) return;
    this.metaSetupBusy = true; this.errorMessage = '';
    this.onboarding.applyOnboardingAction(this.projectId, {
      action: 'defer_meta_setup', question_message_id: message.id, client_action_id: this.createClientMessageId(),
    }).subscribe({
      next: (turn) => { this.metaSetupBusy = false; this.applyTurn(turn); this.scrollToBottom(); },
      error: (error: HttpErrorResponse) => {
        this.metaSetupBusy = false;
        this.handleStructuredActionError(error, 'The Meta setup decision could not be saved.');
      },
    });
  }

  startConversation(): void {
    this.showWelcome = false;
    this.isAnalyzing = true;
    this.onboarding.startChat(this.projectId).subscribe({
      next: (turn) => { this.applyTurn(turn); this.isAnalyzing = false; this.scrollToBottom(); },
      error: () => { this.isAnalyzing = false; this.errorMessage = 'The Project Assistant could not start.'; },
    });
  }
  beginWithWebsite(url: string): void {
    this.showWelcome = false; this.isAnalyzing = true;
    this.onboarding.bootstrap(this.projectId, url).subscribe({
      next: (turn) => {
        this.applyTurn(turn); this.isAnalyzing = false; this.scrollToBottom();
        this.schedulePolling();
      },
      error: () => { this.showWelcome = true; this.isAnalyzing = false; this.errorMessage = 'The website could not be processed. You can retry or continue without it.'; },
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
    return !this.hasPendingReview && message.sender === 'ai' && !!message.ui_payload && !message.response_payload
      && this.visibleMessages.filter((item) => item.sender === 'ai' && !!item.ui_payload && !item.response_payload).at(-1) === message;
  }

  get hasPendingReview(): boolean {
    return this.sources.some((source) => this.isReviewableSource(source) && this.hasPendingProposals(source));
  }
  get visibleMessages(): ChatMessage[] {
    if (!this.hasPendingReview) return this.messages;
    return this.messages.filter((message) => !(
      message.sender === 'ai' && !!message.ui_payload && !message.response_payload
    ));
  }
  sourcesForMessage(messageId?: string): ProjectSource[] {
    return messageId ? this.sources.filter((source) => source.message_id === messageId && this.isReviewableSource(source)) : [];
  }
  get unlinkedSources(): ProjectSource[] {
    const messageIds = new Set(this.messages.flatMap((message) => message.id ? [message.id] : []));
    return this.sources.filter((source) => this.isReviewableSource(source) && (!source.message_id || !messageIds.has(source.message_id)));
  }
  isReviewableSource(source: ProjectSource): boolean {
    return !(source.kind === 'image' && !!source.url);
  }
  hasPendingProposals(source: ProjectSource): boolean {
    return source.proposals.some((proposal) => proposal.status === 'pending');
  }
  isSourceExpanded(source: ProjectSource): boolean {
    return source.status === 'failed'
      || this.hasPendingProposals(source)
      || this.expandedSourceIds.has(source.id);
  }
  onSourceToggle(source: ProjectSource, event: Event): void {
    if (this.hasPendingProposals(source)) return;
    const details = event.currentTarget as HTMLDetailsElement;
    if (details.open) this.expandedSourceIds.add(source.id);
    else this.expandedSourceIds.delete(source.id);
  }
  handleKeyDown(event: KeyboardEvent): void { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); if (this.canSend) this.sendMessage(); } }
  sendMessage(): void {
    if (!this.canSend) return;
    if (this.isRecording) this.speech.stop();
    const content = this.prompt.trim();
    const files = [...this.selectedFiles];
    const clientMessageId = this.retryClientMessageId || this.createClientMessageId();
    const optimistic: ChatMessage = {
      id: clientMessageId,
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
    this.messages = [...this.messages, optimistic]; this.isAnalyzing = true; this.isUploading = !!files.length; this.scrollToBottom();
    const request = files.length
      ? this.onboarding.sendMessageWithFiles(this.projectId, content, files, this.replyToMessageId, clientMessageId)
      : this.onboarding.sendMessage(this.projectId, content, this.replyToMessageId, clientMessageId);
    const replyTo = this.replyToMessageId;
    this.replyToMessageId = null;
    request.subscribe({
      next: (turn) => {
        this.retryClientMessageId = null;
        this.messages = this.messages.filter((message) => message !== optimistic);
        this.markReply(replyTo, content);
        this.applyTurn(turn);
        this.isAnalyzing = false; this.isUploading = false; this.scrollToBottom();
      },
      error: (error: HttpErrorResponse) => {
        this.messages = this.messages.filter((message) => message !== optimistic);
        this.recoverFailedSend(error, content, files, replyTo, clientMessageId);
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
    if (!this.speechSupported || this.isAnalyzing) return;
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
    if (proposal.submitting || proposal.status !== 'pending') return;
    if (action === 'confirm' && !this.proposalCanConfirm(proposal)) return;
    if (action === 'correct' && !this.proposalCanSave(proposal)) return;
    const anchor = captureReviewScrollAnchor(this.chatScroll?.nativeElement, proposal.id);
    const nextProposalId = source.proposals.find(item => item.status === 'pending' && item.id !== proposal.id)?.id || null;
    const value = action === 'correct' ? this.parseValue(proposal.draftValue || '') : undefined;
    this.errorMessage = '';
    this.updateProposal(source.id, proposal.id, { submitting: true, inlineError: undefined });
    this.onboarding.decideProposal(this.projectId, proposal.id, action, value).subscribe({
      next: (result) => {
        this.updateProposal(source.id, proposal.id, {
          ...result.proposal,
          draftValue: this.formatValue(result.proposal.value),
          submitting: false,
          inlineError: undefined,
        });
        this.profile = result.profile;
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
          const message = this.apiDetail(error, 'That proposal could not be updated.');
          this.updateProposal(source.id, proposal.id, {
            submitting: false,
            inlineError: message,
            validation: error.status === 422 && typeof error.error?.detail === 'object'
              ? error.error.detail
              : proposal.validation,
          });
          this.restoreProposalContext(anchor, proposal.id);
        }
      },
    });
  }

  onProposalDraftChange(source: ProjectSource, proposal: SourceProposal, value: string): void {
    this.updateProposal(source.id, proposal.id, { draftValue: value, inlineError: undefined });
  }
  proposalDraftError(proposal: SourceProposal): string {
    return proposal.inlineError || validateProposalDraft(proposal)['value'] || '';
  }
  proposalCanConfirm(proposal: SourceProposal): boolean {
    return !proposal.submitting && !proposal.validation;
  }
  proposalCanSave(proposal: SourceProposal): boolean {
    return !proposal.submitting
      && (proposal.draftValue || '').trim() !== this.formatValue(proposal.value).trim()
      && !this.proposalDraftError(proposal);
  }

  retrySource(source: ProjectSource): void {
    if (source.status !== 'failed') return;
    this.errorMessage = '';
    this.onboarding.retrySource(this.projectId, source.id).subscribe({
      next: (updated) => {
        this.mergeSources([updated]);
        this.schedulePolling();
      },
      error: () => {
        this.errorMessage = 'The website could not be queued again. Check its URL or try later.';
      },
    });
  }

  selectCoverCandidate(source: ProjectSource): void {
    if (source.kind !== 'image' || this.coverBusy) return;
    this.selectedCoverSourceId = source.id;
    this.errorMessage = '';
    this.cdr.detectChanges();
  }

  uploadCoverCandidate(event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    input.value = '';
    if (!file || this.coverUploadBusy || this.coverBusy) return;
    if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) {
      this.errorMessage = 'Use a JPG, PNG, or WEBP image for the Project cover.';
      return;
    }
    this.coverUploadBusy = true;
    this.errorMessage = '';
    this.onboarding.uploadCover(this.projectId, file).subscribe({
      next: source => {
        this.coverUploadBusy = false;
        this.mergeSources([source]);
        this.selectedCoverSourceId = source.id;
        this.cdr.detectChanges();
      },
      error: (error: HttpErrorResponse) => {
        this.coverUploadBusy = false;
        this.errorMessage = this.apiDetail(error, 'The cover image could not be uploaded.');
        this.cdr.detectChanges();
      },
    });
  }

  confirmProjectCover(): void {
    if (!this.selectedCoverSourceId || this.coverBusy) return;
    this.coverBusy = true;
    this.onboarding.setCover(this.projectId, this.selectedCoverSourceId).subscribe({
      next: () => {
        const selectedId = this.selectedCoverSourceId;
        this.coverBusy = false;
        this.sources = this.sources.map((item) => ({ ...item, is_primary: item.id === selectedId }));
        this.syncState('bottom');
        this.cdr.detectChanges();
      },
      error: () => { this.coverBusy = false; this.errorMessage = 'That image could not be selected as the Project cover.'; },
    });
  }

  confirmPropertyCatalog(): void {
    if (this.confirmingPropertyCatalog || !this.catalogReady) return;
    this.confirmingPropertyCatalog = true;
    this.onboarding.confirmPropertyTypeCatalog(this.projectId).pipe(
      timeout(20_000),
      finalize(() => { this.confirmingPropertyCatalog = false; this.cdr.detectChanges(); }),
    ).subscribe({
      next: catalog => {
        this.propertyCatalog = catalog;
        this.syncState('bottom');
      },
      error: (error: HttpErrorResponse) => {
        this.errorMessage = this.apiDetail(error, 'Review every property type before completing the catalog.');
      },
    });
  }

  completeOnboarding(): void {
    if (!this.profile.completion.ready_for_confirmation || this.isCompleting) return;
    this.isCompleting = true; this.errorMessage = '';
    this.onboarding.complete(this.projectId).subscribe({
      next: (result) => this.router.navigateByUrl(result.redirect_url),
      error: (error: HttpErrorResponse) => {
        this.isCompleting = false;
        this.errorMessage = error.status === 409
          ? 'The profile changed and needs another review before it can be completed.'
          : 'The onboarding could not be completed. Please try again.';
        if (error.status === 409) this.syncState();
        this.cdr.detectChanges();
      },
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
  statusIcon(status: ValidationStatus): string { return ({ confirmed: 'check_circle', corrected_by_user: 'check_circle', not_applicable: 'remove_circle', deferred: 'schedule', conflicting: 'error', stale: 'history', expired: 'event_busy', pending_confirmation: 'schedule', extracted: 'manage_search', missing: 'radio_button_unchecked' })[status]; }
  statusClass(status: ValidationStatus): string { if (status === 'confirmed' || status === 'corrected_by_user') return 'text-green-400'; if (status === 'conflicting' || status === 'expired') return 'text-red-400'; if (status === 'stale' || status === 'pending_confirmation' || status === 'extracted') return 'text-secondary'; return 'text-gray-600'; }
  statusLabel(status: ValidationStatus): string { return status.replaceAll('_', ' '); }
  formatValue(value: unknown): string { return typeof value === 'string' ? value : value == null ? '' : JSON.stringify(value); }
  trackSource(_: number, item: ProjectSource): string { return item.id; }
  trackProposal(_: number, item: SourceProposal): string { return item.id; }
  trackField(_: number, item: ProjectFieldProgress): string { return item.key; }

  private parseValue(value: string): unknown { const trimmed = value.trim(); try { return /^[\[{]/.test(trimmed) ? JSON.parse(trimmed) : trimmed; } catch { return trimmed; } }
  private createClientMessageId(): string {
    if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (character) => {
      const random = Math.floor(Math.random() * 16);
      const value = character === 'x' ? random : (random & 0x3) | 0x8;
      return value.toString(16);
    });
  }
  private restoreFailedSend(
    content: string, files: File[], replyTo: string | null, clientMessageId: string, message: string,
  ): void {
    this.prompt = content; this.selectedFiles = files; this.replyToMessageId = replyTo;
    this.retryClientMessageId = clientMessageId;
    this.isAnalyzing = false; this.isUploading = false; this.errorMessage = message;
    this.cdr.detectChanges();
  }
  private recoverFailedSend(
    error: HttpErrorResponse, content: string, files: File[], replyTo: string | null, clientMessageId: string,
  ): void {
    const uncertainDelivery = [0, 409, 502, 503, 504].includes(error.status);
    if (!uncertainDelivery) {
      const message = error.status === 422
        ? 'That answer is not valid for the current question. Review it and try again.'
        : 'The message could not be processed. Your text and selected files were restored.';
      this.restoreFailedSend(content, files, replyTo, clientMessageId, message);
      return;
    }
    this.onboarding.getState(this.projectId).subscribe({
      next: (state) => {
        const saved = state.messages.some((message) => message.id === clientMessageId);
        if (!saved) {
          this.restoreFailedSend(
            content, files, replyTo, clientMessageId,
            'The connection was interrupted. Your text and selected files were restored so you can retry safely.',
          );
          return;
        }
        this.retryClientMessageId = null;
        this.applyState(state);
        this.isAnalyzing = false; this.isUploading = false;
        this.errorMessage = 'Your answer was saved. The current onboarding state has been restored.';
        this.cdr.detectChanges();
      },
      error: () => this.restoreFailedSend(
        content, files, replyTo, clientMessageId,
        'The connection was interrupted. Your text and selected files were restored so you can retry safely.',
      ),
    });
  }
  private handleStructuredActionError(error: HttpErrorResponse, fallback: string): void {
    this.errorMessage = typeof error.error?.detail === 'string' ? error.error.detail : fallback;
    if ([0, 409, 502, 504].includes(error.status)) this.syncState();
    this.cdr.detectChanges();
  }
  private isResolvedStatus(status: ValidationStatus): boolean {
    return ['confirmed', 'corrected_by_user', 'not_applicable', 'deferred'].includes(status);
  }
  private joinSpeech(base: string, finalText: string, interimText: string): string {
    return [base, finalText, interimText].filter(Boolean).join(' ').replace(/\s+/g, ' ').trimStart();
  }
  private prepareSources(items: ProjectSource[]): ProjectSource[] {
    const previousProposals = new Map(
      this.sources.flatMap((source) => source.proposals.map((proposal) => [proposal.id, proposal] as const)),
    );
    return items.map((source) => ({
      ...source,
      proposals: source.proposals.map((proposal) => {
        const previous = previousProposals.get(proposal.id);
        const preserveDraft = proposal.status === 'pending'
          && previous?.status === 'pending'
          && previous.draftValue !== undefined;
        return {
          ...proposal,
          draftValue: preserveDraft ? previous.draftValue : this.formatValue(proposal.value),
          inlineError: preserveDraft ? previous.inlineError : undefined,
        };
      }),
    }));
  }
  private mergeSources(items: ProjectSource[]): void {
    const merged = new Map(this.sources.map((source) => [source.id, source]));
    for (const source of this.prepareSources(items)) merged.set(source.id, source);
    this.sources = Array.from(merged.values());
    for (const source of this.sources) if (this.hasPendingProposals(source)) this.expandedSourceIds.add(source.id);
    this.loadSourceImagePreviews();
  }
  private syncState(
    scrollMode: OnboardingScrollMode = 'none',
    anchor: ReviewScrollAnchor | null = null,
  ): void {
    const shouldScrollToBottom = scrollMode === 'bottom'
      || (scrollMode === 'auto' && isNearScrollBottom(this.chatScroll?.nativeElement));
    this.onboarding.getState(this.projectId).subscribe({
      next: (state) => {
        this.initialState = 'ready';
        this.applyState(state);
        if (scrollMode === 'preserve') this.restoreProposalAnchor(anchor);
        else if (shouldScrollToBottom) this.scrollToBottom();
      },
      error: (error: HttpErrorResponse) => {
        if (error.status !== 401) {
          this.initialState = 'error';
          this.errorMessage = 'The Project Onboarding state could not be synchronized.';
          this.cdr.detectChanges();
        }
      },
    });
  }
  private applyState(state: OnboardingState): void {
    if (state.version < this.lastStateVersion) return;
    this.lastStateVersion = state.version;
    this.messages = [...state.messages]; this.profile = state.profile;
    this.sources = this.prepareSources(state.sources); this.nextQuestion = state.next_question;
    this.loadSourceImagePreviews();
    this.loadPropertyTypes();
    for (const source of this.sources) if (this.hasPendingProposals(source)) this.expandedSourceIds.add(source.id);
    this.showWelcome = state.stage === 'website';
    if (this.pollingTimer) clearTimeout(this.pollingTimer);
    if (state.stage === 'processing') this.schedulePolling();
    else this.pollingStartedAt = 0;
    this.cdr.detectChanges();
  }
  private applyTurn(turn: ChatTurn): void {
    const additions = [turn.user_message, turn.message].filter((message): message is ChatMessage => !!message);
    const withIds = new Map(this.messages.filter((message) => message.id).map((message) => [message.id!, message]));
    for (const message of additions) if (message.id) withIds.set(message.id, message);
    this.messages = [...withIds.values(), ...this.messages.filter((message) => !message.id), ...additions.filter((message) => !message.id)];
    this.profile = turn.profile; this.nextQuestion = turn.next_question; this.mergeSources(turn.sources); this.cdr.detectChanges();
    if (turn.sources.some((source) => source.status === 'processing')) this.schedulePolling();
    if (turn.redirect_url) this.router.navigateByUrl(turn.redirect_url);
  }
  private updateProposal(sourceId: string, proposalId: string, patch: Partial<SourceProposal>): void {
    this.sources = this.sources.map((source) => source.id !== sourceId ? source : ({
      ...source,
      proposals: source.proposals.map((item) => item.id === proposalId ? { ...item, ...patch } : item),
    }));
    this.cdr.detectChanges();
  }
  private loadSourceImagePreviews(): void {
    for (const source of this.sources) {
      if (source.kind !== 'image' || source.status !== 'ready' || !source.download_url || this.sourceImageUrls.has(source.id)) continue;
      this.onboarding.downloadAttachment(source.download_url).subscribe({
        next: blob => { this.sourceImageUrls.set(source.id, URL.createObjectURL(blob)); this.cdr.detectChanges(); },
      });
    }
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
      const choices = message.ui_payload.options.length ? message.ui_payload.options : message.ui_payload.examples;
      const selected = choices.find((item) => item.toLocaleLowerCase() === answer.toLocaleLowerCase()) || null;
      return { ...message, response_payload: { status: 'answered', answer, selected_option: selected, custom: !selected } };
    });
  }
  private scrollToBottom(): void { setTimeout(() => { const element = this.chatScroll?.nativeElement; if (element) element.scrollTop = element.scrollHeight; this.cdr.detectChanges(); }, 100); }
}
