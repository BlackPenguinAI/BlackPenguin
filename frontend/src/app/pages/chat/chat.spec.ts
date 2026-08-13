import { ComponentFixture, TestBed } from '@angular/core/testing';
import { HttpClientTestingModule, HttpTestingController } from '@angular/common/http/testing';
import { TranslateModule } from '@ngx-translate/core';
import { provideRouter } from '@angular/router';

import { ChatComponent } from './chat';
import { EMPTY_COMPANY_PROFILE } from './company-onboarding.models';


describe('ChatComponent', () => {
  let component: ChatComponent;
  let fixture: ComponentFixture<ChatComponent>;
  let http: HttpTestingController;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [ChatComponent, HttpClientTestingModule, TranslateModule.forRoot()],
      providers: [provideRouter([])],
    }).compileComponents();

    fixture = TestBed.createComponent(ChatComponent);
    component = fixture.componentInstance;
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    http.verify();
    localStorage.clear();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('should not render the chat before the initial state is loaded', () => {
    expect(component.initialState).toBe('loading');
    expect(component.showWelcome).toBe(false);
  });

  it('should replace the composer with a Projects action after final approval', () => {
    const completedProfile = {
      ...EMPTY_COMPANY_PROFILE,
      completion: {
        ...EMPTY_COMPANY_PROFILE.completion,
        percentage: 100,
        can_complete: true,
        final_approved: true,
        required: { completed: 10, total: 10, remaining: 0 },
        conditional: { completed: 0, total: 5, evaluated: 5, applicable: 0, remaining: 0 },
      },
    };
    fixture.detectChanges();
    http.expectOne('http://localhost:8000/api/v1/company-onboarding/chat/state').flush({
      messages: [], profile: completedProfile, sources: [], stage: 'complete', version: 1,
      team: { administrator: null, members: [], roles: [] },
      next_question: {
        field: null, label: 'Company Profile complete',
        prompt: 'Your Company Profile is approved. Continue to Projects when you are ready.',
        input_type: 'complete', options: [], examples: [], allow_custom: false,
        minimum_words: null,
      },
    });
    fixture.detectChanges();

    const element = fixture.nativeElement as HTMLElement;
    expect(element.querySelector('[data-testid="company-onboarding-complete"]')).not.toBeNull();
    expect(element.textContent).toContain('Continue to Projects');
    expect(element.querySelector('textarea')).toBeNull();
  });

  it('should expose required and conditional fields separately', () => {
    component.profile = {
      ...EMPTY_COMPANY_PROFILE,
      fields: [
        {
          key: 'official_company_name',
          label: 'Official company name',
          requirement: 'required',
          status: 'confirmed',
          applicable: null,
        },
        {
          key: 'dba',
          label: 'DBA (Doing Business As)',
          requirement: 'conditionally_required',
          status: 'not_applicable',
          applicable: false,
        },
      ],
    };

    expect(component.requiredFields.map((field) => field.key)).toEqual(['official_company_name']);
    expect(component.conditionalFields.map((field) => field.key)).toEqual(['dba']);
  });

  it('should use distinct icons for confirmed, pending and conflicting fields', () => {
    expect(component.statusIcon('confirmed')).toBe('check_circle');
    expect(component.statusIcon('pending_confirmation')).toBe('schedule');
    expect(component.statusIcon('conflicting')).toBe('error');
  });

  it('should expose onboarding status labels in English', () => {
    expect(component.statusLabel('missing')).toBe('Missing');
    expect(component.statusLabel('pending_confirmation')).toBe('Pending confirmation');
    expect(component.statusLabel('not_applicable')).toBe('Not applicable');
    expect(component.statusLabel('deferred')).toBe('Provide later');
  });

  it('should expose team progress labels without duplicating corporate contacts', () => {
    expect(component.teamStatusLabel('confirmed')).toBe('Configured');
    expect(component.teamStatusLabel('deferred')).toBe('Configure later');
    expect(component.teamStatusLabel('not_applicable')).toBe('Not needed now');
  });

  it('should not keep a chat question active while Team owns the workflow', () => {
    component.currentStage = 'team';
    const staleQuestion = {
      id: 'legal-question',
      sender: 'ai' as const,
      content: 'Choose the best option for Legal company name.',
      created_at: new Date(),
      attachments: [],
      ui_payload: {
        field: 'legal_company_name', label: 'Legal company name', prompt: 'Legal company name?',
        input_type: 'text' as const, options: [], examples: [], allow_custom: true,
        minimum_words: null,
      },
    };
    component.messages = [staleQuestion];

    expect(component.isActiveQuestion(staleQuestion)).toBe(false);
    expect(component.hasExclusiveStep).toBe(true);
  });

  it('should save public contact information as structured lists', () => {
    component.currentStage = 'enrichment';
    component.publicEmails = 'info@example.com, sales@example.com';
    component.publicPhones = '+1 305 555 0100';
    component.socialProfiles = 'https://linkedin.com/company/example\nhttps://instagram.com/example';

    component.savePublicPresence();

    const request = http.expectOne('http://localhost:8000/api/v1/company-onboarding/profile');
    expect(request.request.method).toBe('PATCH');
    expect(request.request.body.updates.map((item: { field: string }) => item.field)).toEqual([
      'public_contact_emails', 'public_contact_phones', 'corporate_social_profiles',
    ]);
    expect(request.request.body.updates[0].value).toEqual(['info@example.com', 'sales@example.com']);
    request.flush(EMPTY_COMPANY_PROFILE);
    http.expectOne('http://localhost:8000/api/v1/company-onboarding/chat/state').flush({
      messages: [], profile: EMPTY_COMPANY_PROFILE, sources: [], stage: 'approval', version: 1,
      team: { administrator: null, members: [], roles: [] },
      next_question: { field: null, label: 'Final approval', prompt: 'Approve', input_type: 'boolean', options: [], examples: [], allow_custom: true, minimum_words: null },
    });
    expect(component.publicPresenceSaved).toBe(true);
  });

  it('should create onboarding users through the shared company user store', () => {
    component.currentStage = 'team';
    component.teamInvite = {
      first_name: 'Ana', last_name: 'Sales', email: 'ana@example.com', role: 'sales',
    };

    component.inviteTeamMember();

    const create = http.expectOne('http://localhost:8000/api/v1/company-onboarding/team/members');
    expect(create.request.body).toEqual(component.teamInvite);
    create.flush({
      id: 'user-1', first_name: 'Ana', last_name: 'Sales', email: 'ana@example.com',
      role: 'sales', is_active: true,
    });
    http.expectOne('http://localhost:8000/api/v1/company-onboarding/team').flush({
      administrator: null,
      members: [{ id: 'user-1', first_name: 'Ana', last_name: 'Sales', email: 'ana@example.com', role: 'sales', is_active: true }],
      roles: [{ role: 'sales', label: 'Sales users', status: 'confirmed', active_users: 1 }],
    });
    http.expectOne('http://localhost:8000/api/v1/company-onboarding/chat/state').flush({
      messages: [], profile: EMPTY_COMPANY_PROFILE, sources: [], stage: 'team', version: 1,
      team: { administrator: null, members: [{ id: 'user-1', first_name: 'Ana', last_name: 'Sales', email: 'ana@example.com', role: 'sales', is_active: true }], roles: [] },
      next_question: null,
    });
    expect(component.team.members[0].email).toBe('ana@example.com');
  });

  it('should render extracted list proposals without JSON syntax', () => {
    expect(component.formatProposalValue({
      field: 'corporate_social_profiles',
      value: ['https://instagram.com/example', 'https://linkedin.com/company/example'],
    })).toBe('https://instagram.com/example, https://linkedin.com/company/example');
  });

  it('should defer all remaining team roles from the Team stage', () => {
    component.currentStage = 'team';
    component.deferRemainingTeamRoles();

    http.expectOne('http://localhost:8000/api/v1/company-onboarding/team/defer-remaining').flush({
      administrator: null, members: [],
      roles: [{ role: 'assistant', label: 'Assistant users', status: 'deferred', active_users: 0 }],
    });
    http.expectOne('http://localhost:8000/api/v1/company-onboarding/chat/state').flush({
      messages: [], profile: EMPTY_COMPANY_PROFILE, sources: [], stage: 'conditional', version: 1,
      team: { administrator: null, members: [], roles: [] },
      next_question: { field: 'dba', label: 'DBA', prompt: 'DBA?', input_type: 'text', options: [], examples: [], allow_custom: true, minimum_words: null },
    });
    expect(component.currentStage).toBe('conditional');
  });

  it('should not expose the removed session initializer', () => {
    expect((component as unknown as { initSession?: unknown }).initSession).toBeUndefined();
  });

  it('should render assistant markdown instead of exposing formatting tokens', () => {
    const html = component.renderMarkdown('Updated **Official company name**.');
    expect(html).toContain('<strong>Official company name</strong>');
    expect(html).not.toContain('**Official');
  });

  it('should keep generic structured source values available for editing', () => {
    expect(component.formatValue({ exists: false, url: null })).toBe('{"exists":false,"url":null}');
  });

  it('should present official website proposals as user-friendly values', () => {
    expect(component.formatProposalValue({
      field: 'official_corporate_website', value: { exists: true, url: 'https://cbhhomes.com/' },
    })).toBe('https://cbhhomes.com/');
    expect(component.formatProposalValue({
      field: 'official_corporate_website', value: { exists: false, url: null },
    })).toBe('No official website');
  });

  it('should automatically link typed text to the latest active question', () => {
    component.messages = [{
      id: 'question-dba', sender: 'ai', content: 'What is the DBA?', created_at: new Date(), attachments: [],
      ui_payload: {
        field: 'dba', label: 'DBA (Doing Business As)', prompt: 'Enter the registered business name.',
        input_type: 'conditional_text', options: [], examples: [], allow_custom: true,
        minimum_words: null,
      },
    }];
    component.prompt = 'CBH Homes';

    component.sendMessage();

    const request = http.expectOne('http://localhost:8000/api/v1/company-onboarding/chat');
    expect(request.request.body).toEqual({
      message: 'CBH Homes', in_reply_to_message_id: 'question-dba',
    });
    request.flush({}, { status: 500, statusText: 'Expected test response' });
  });

  it('should restore the structured website contract when saving an edit', () => {
    const proposal = {
      id: 'proposal-website', field: 'official_corporate_website', label: 'Official website',
      value: { exists: true, url: 'https://old.example.com/' }, draftValue: 'https://cbhhomes.com/',
      evidence: null, confidence: 'high' as const, status: 'pending' as const,
    };
    const source = {
      id: 'source-website', kind: 'official_website' as const, status: 'ready' as const,
      name: 'cbhhomes.com', url: 'https://cbhhomes.com/', mime_type: 'text/html', size_bytes: 100,
      message_id: null, download_url: null, error_message: null, proposals: [proposal],
      created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
    };
    component.sources = [source];

    component.decideProposal(source, proposal, 'correct');

    const request = http.expectOne('http://localhost:8000/api/v1/company-onboarding/proposals/proposal-website/decision');
    expect(request.request.body).toEqual({
      action: 'correct', value: { exists: true, url: 'https://cbhhomes.com/' },
    });
    request.flush({
      proposal: { ...proposal, value: request.request.body.value, status: 'corrected' },
      profile: EMPTY_COMPANY_PROFILE,
    });
    http.expectOne('http://localhost:8000/api/v1/company-onboarding/chat/state').flush({
      messages: [], profile: EMPTY_COMPANY_PROFILE, sources: [], stage: 'required', version: 1,
      next_question: {
        field: null, label: 'Final approval', prompt: 'Approve', input_type: 'boolean',
        options: [], examples: [], allow_custom: true, minimum_words: null,
      },
    });
  });

  it('should preserve review position and keep the source expanded after the last decision', () => {
    const proposal = {
      id: 'proposal-last', field: 'headquarters', label: 'Headquarters',
      value: 'Miami', draftValue: 'Miami', evidence: null, confidence: 'high' as const,
      status: 'pending' as const,
    };
    const source = {
      id: 'source-last', kind: 'official_website' as const, status: 'ready' as const,
      name: 'example.com', url: 'https://example.com', mime_type: 'text/html', size_bytes: 100,
      message_id: null, download_url: null, error_message: null, proposals: [proposal],
      created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
    };
    component.sources = [source];
    (component as unknown as { expandedSourceIds: Set<string> }).expandedSourceIds.add(source.id);
    const scrollToBottom = vi.spyOn(component as unknown as { scrollToBottom(): void }, 'scrollToBottom');

    component.decideProposal(source, proposal, 'confirm');
    http.expectOne('http://localhost:8000/api/v1/company-onboarding/proposals/proposal-last/decision').flush({
      proposal: { ...proposal, status: 'confirmed' }, profile: EMPTY_COMPANY_PROFILE,
    });
    http.expectOne('http://localhost:8000/api/v1/company-onboarding/chat/state').flush({
      messages: [], profile: EMPTY_COMPANY_PROFILE,
      sources: [{ ...source, proposals: [{ ...proposal, status: 'confirmed' }] }],
      stage: 'required', version: 1, team: { administrator: null, members: [], roles: [] },
      next_question: { field: 'primary_business_model', label: 'Business model', prompt: 'Business model?', input_type: 'text', options: [], examples: [], allow_custom: true, minimum_words: null },
    });

    expect(scrollToBottom).not.toHaveBeenCalled();
    expect(component.sources[0].proposals[0].status).toBe('confirmed');
    expect(component.isSourceExpanded(component.sources[0])).toBe(true);
  });

  it('should keep an unsaved proposal draft while another decision synchronizes state', () => {
    const preservedDraft = {
      id: 'proposal-draft', field: 'headquarters', label: 'Headquarters', value: 'Miami',
      draftValue: 'Lima, Peru', evidence: null, confidence: 'high' as const, status: 'pending' as const,
    };
    component.sources = [{
      id: 'source-draft', kind: 'official_website', status: 'ready', name: 'example.com',
      url: 'https://example.com', mime_type: 'text/html', size_bytes: 100,
      message_id: null, download_url: null, error_message: null, proposals: [preservedDraft],
      created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
    }];

    (component as unknown as { applyState(state: unknown): void }).applyState({
      messages: [], profile: EMPTY_COMPANY_PROFILE,
      sources: [{ ...component.sources[0], proposals: [{ ...preservedDraft, draftValue: undefined }] }],
      stage: 'website_review', version: 1, team: { administrator: null, members: [], roles: [] },
      next_question: { field: null, label: 'Review', prompt: 'Review', input_type: 'text', options: [], examples: [], allow_custom: true, minimum_words: null },
    });

    expect(component.sources[0].proposals[0].draftValue).toBe('Lima, Peru');
  });

  it('should keep proposal actions available and show a structured validation error', () => {
    const proposal = {
      id: 'proposal-description', field: 'approved_short_company_description', label: 'Description',
      value: 'Short', draftValue: 'Short', evidence: null, confidence: 'high' as const,
      status: 'pending' as const,
    };
    const source = {
      id: 'source-description', kind: 'official_website' as const, status: 'ready' as const,
      name: 'cbhhomes.com', url: 'https://cbhhomes.com/', mime_type: 'text/html', size_bytes: 100,
      message_id: null, download_url: null, error_message: null, proposals: [proposal],
      created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
    };
    component.sources = [source];

    component.decideProposal(source, proposal, 'confirm');
    const request = http.expectOne('http://localhost:8000/api/v1/company-onboarding/proposals/proposal-description/decision');
    request.flush({
      detail: { code: 'minimum_characters', message: 'Enter at least 25 characters.' },
    }, { status: 422, statusText: 'Unprocessable Content' });

    expect(component.sources[0].proposals[0].submitting).toBe(false);
    expect(component.sources[0].proposals[0].status).toBe('pending');
    expect(component.sources[0].proposals[0].errorMessage).toBe('Enter at least 25 characters.');
  });

  it('should confirm every unchanged website proposal sequentially', () => {
    const proposals = [
      { id: 'proposal-1', field: 'official_company_name', label: 'Name', value: 'Example', evidence: null, confidence: 'high' as const, status: 'pending' as const },
      { id: 'proposal-2', field: 'headquarters', label: 'Headquarters', value: 'Miami', evidence: null, confidence: 'high' as const, status: 'pending' as const },
    ];
    const source = {
      id: 'source-1', kind: 'official_website' as const, status: 'ready' as const,
      name: 'example.com', url: 'https://example.com', mime_type: 'text/html', size_bytes: 100,
      message_id: null, download_url: null, error_message: null, proposals,
      created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
    };
    component.sources = [source];

    component.confirmAllUnchanged(source);
    const first = http.expectOne('http://localhost:8000/api/v1/company-onboarding/proposals/proposal-1/decision');
    first.flush({ proposal: { ...proposals[0], status: 'confirmed' }, profile: EMPTY_COMPANY_PROFILE });
    const second = http.expectOne('http://localhost:8000/api/v1/company-onboarding/proposals/proposal-2/decision');
    second.flush({ proposal: { ...proposals[1], status: 'confirmed' }, profile: EMPTY_COMPANY_PROFILE });
    http.expectOne('http://localhost:8000/api/v1/company-onboarding/chat/state').flush({
      messages: [], profile: EMPTY_COMPANY_PROFILE, sources: [], stage: 'required', version: 1,
      team: { administrator: null, members: [], roles: [] },
      next_question: { field: 'preferred_display_name', label: 'Display name', prompt: 'Display name?', input_type: 'text', options: [], examples: [], allow_custom: true, minimum_words: null },
    });

    expect(component.confirmingSourceIds.has(source.id)).toBe(false);
  });

  it('should anchor pending source review to its message and hide the next question', () => {
    component.messages = [
      { id: 'message-1', sender: 'user', content: 'https://example.com', created_at: new Date(), attachments: [] },
      {
        id: 'question-1', sender: 'ai', content: 'Next question', created_at: new Date(), attachments: [],
        ui_payload: { field: 'voice', label: 'Voice', prompt: 'Next question', input_type: 'text', options: [], examples: [], allow_custom: true, minimum_words: null },
      },
    ];
    component.sources = [{
      id: 'source-1', kind: 'official_website', status: 'ready', name: 'example.com',
      url: 'https://example.com', mime_type: 'text/html', size_bytes: 100,
      message_id: 'message-1', download_url: null, error_message: null,
      proposals: [{ id: 'proposal-1', field: 'official_company_name', label: 'Name', value: 'Example', evidence: null, confidence: 'high', status: 'pending' }],
      created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
    }];
    component.prompt = 'Should not send';

    expect(component.sourcesForMessage('message-1').map((source) => source.id)).toEqual(['source-1']);
    expect(component.unlinkedSources).toEqual([]);
    expect(component.visibleMessages.map((message) => message.id)).toEqual(['message-1']);
    expect(component.isSourceExpanded(component.sources[0])).toBe(true);
    expect(component.canSend).toBe(false);
  });

  it('offers a failed official URL as user-confirmed website only until it is saved', () => {
    const source = {
      id: 'source-1', kind: 'official_website' as const, status: 'failed' as const,
      name: 'www.highlandhomes.com', url: 'https://www.highlandhomes.com/',
      mime_type: 'text/html', size_bytes: 100, message_id: 'message-1', download_url: null,
      error_message: 'This website requires browser security verification.', proposals: [],
      created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
    };

    expect(component.canUseAsOfficialWebsite(source)).toBe(true);
    component.profile = {
      ...EMPTY_COMPANY_PROFILE,
      data: { official_corporate_website: source.url },
    };
    expect(component.canUseAsOfficialWebsite(source)).toBe(false);
  });

  it('expands a failed uploaded file without blocking the composer', () => {
    const source = {
      id: 'source-failed', kind: 'uploaded_file' as const, status: 'failed' as const,
      name: 'protected.pdf', url: null, mime_type: 'application/pdf', size_bytes: 100,
      message_id: 'message-1', download_url: '/file',
      error_message: "I couldn't analyze this file because it is password-protected.", proposals: [],
      created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
    };
    component.sources = [source];
    component.prompt = 'Continue manually';

    expect(component.isSourceExpanded(source)).toBe(true);
    expect(component.hasPendingReview).toBe(false);
    expect(component.canSend).toBe(true);
  });
});
