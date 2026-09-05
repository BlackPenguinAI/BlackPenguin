import { ComponentFixture, TestBed } from '@angular/core/testing';
import { HttpClientTestingModule, HttpTestingController } from '@angular/common/http/testing';
import { TranslateModule } from '@ngx-translate/core';
import { provideRouter } from '@angular/router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

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
    for (const request of http.match((candidate) => candidate.url.endsWith('/company-onboarding/media'))) {
      request.flush([]);
    }
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

  it('should keep the composer available for post-approval Company edits', () => {
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
    expect(element.textContent).toContain('Back to Company Overview');
    expect(element.textContent).toContain('continue using the chat to update');
    expect(element.querySelector('textarea')).not.toBeNull();
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

  it('refreshes extracted public presence values until the user edits that field', () => {
    (component as any).initializePublicPresence({ public_contact_phones: ['+1 800 555 0100'] });
    expect(component.publicPhones).toBe('+1 800 555 0100');

    component.markPublicPresenceDirty('public_contact_phones');
    component.publicPhones = '+1 305 555 0100';
    (component as any).initializePublicPresence({ public_contact_phones: ['+1 999 555 0100'] });

    expect(component.publicPhones).toBe('+1 305 555 0100');
  });

  it('asks only for unresolved public presence fields', () => {
    component.profile = {
      ...EMPTY_COMPANY_PROFILE,
      fields: [
        { key: 'public_contact_emails', label: 'Emails', requirement: 'recommended', status: 'missing', applicable: true },
        { key: 'public_contact_phones', label: 'Phones', requirement: 'recommended', status: 'confirmed', applicable: true },
        { key: 'corporate_social_profiles', label: 'Social', requirement: 'recommended', status: 'confirmed', applicable: true },
      ],
    };

    expect(component.editablePublicPresenceFields).toEqual(['public_contact_emails']);
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

  it('should keep logo selection provisional until the user confirms it', () => {
    const asset = {
      id: 'logo-1', role: 'candidate', name: 'logo.png', mime_type: 'image/png', size_bytes: 100,
      source_url: 'https://example.com/logo.png', is_primary: false, review_status: 'candidate',
      image_url: '/api/v1/company-onboarding/media/logo-1/file', created_at: new Date().toISOString(),
    };
    component.currentStage = 'logo_review';
    component.companyMedia = [asset];

    component.selectCompanyLogo(asset);

    expect(component.selectedLogoId).toBe('logo-1');
    http.expectNone('http://localhost:8000/api/v1/company-onboarding/media/logo-1/logo');
  });

  it('exposes the confirmed logo and hides empty superseded assistant messages', () => {
    const asset = {
      id: 'logo-1', role: 'logo', name: 'official-logo.png', mime_type: 'image/png', size_bytes: 100,
      source_url: null, is_primary: true, review_status: 'confirmed',
      image_url: '/api/v1/company-onboarding/media/logo-1/file', created_at: new Date().toISOString(),
    };
    component.companyMedia = [asset];
    component.messages = [
      {
        id: 'legacy-empty', sender: 'ai', content: '', created_at: new Date(), attachments: [],
        ui_payload: { field: 'company_logo', label: 'Logo', prompt: 'Choose logo', input_type: 'company_logo', options: [], examples: [], allow_custom: false, minimum_words: null },
        response_payload: { status: 'superseded', answer: '' },
      },
      { id: 'next-question', sender: 'ai', content: 'What is the headquarters?', created_at: new Date(), attachments: [] },
    ];

    expect(component.selectedCompanyLogo?.id).toBe('logo-1');
    expect(component.visibleMessages.map(message => message.id)).toEqual(['next-question']);
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
    expect(create.request.headers.get('Idempotency-Key')).toMatch(/^company-onboarding-user-/);
    create.flush({
      id: 'user-1', first_name: 'Ana', last_name: 'Sales', email: 'ana@example.com',
      role: 'sales', is_active: true, auth_status: 'invited', invitation_delivery: 'sent',
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
    expect(component.teamInviteAttempted).toBe(false);
    expect(component.teamSuccess).toContain('Invitation sent to ana@example.com');
    expect(component.teamInviteErrorCount).toBe(3);
  });

  it('should reuse its idempotency key when an invitation request is retried', () => {
    component.currentStage = 'team';
    component.teamInvite = {
      first_name: 'Ana', last_name: 'Sales', email: 'ana@example.com', role: 'sales',
      timezone: 'America/Lima', project_access_scope: 'all', project_ids: [],
    };

    component.inviteTeamMember();
    const first = http.expectOne('http://localhost:8000/api/v1/company-onboarding/team/members');
    const firstKey = first.request.headers.get('Idempotency-Key');
    first.flush({ detail: 'Gateway timeout' }, { status: 504, statusText: 'Gateway Timeout' });

    component.inviteTeamMember();
    const retry = http.expectOne('http://localhost:8000/api/v1/company-onboarding/team/members');
    expect(retry.request.headers.get('Idempotency-Key')).toBe(firstKey);
    retry.flush({
      id: 'user-1', first_name: 'Ana', last_name: 'Sales', email: 'ana@example.com',
      role: 'sales', is_active: true, auth_status: 'invited', invitation_delivery: 'sent',
      request_replayed: true,
    });
    http.expectOne('http://localhost:8000/api/v1/company-onboarding/team').flush({
      administrator: null, members: [], roles: [], projects: [],
    });
    http.expectOne('http://localhost:8000/api/v1/company-onboarding/chat/state').flush({
      messages: [], profile: EMPTY_COMPANY_PROFILE, sources: [], stage: 'team', version: 1,
      team: { administrator: null, members: [], roles: [] }, next_question: null,
    });
    expect(component.teamSuccess).toContain('already processed');
  });

  it('shows the safe Firebase code and supports removing a failed invitation', () => {
    component.currentStage = 'team';
    component.teamInvite = {
      first_name: 'Ana', last_name: 'Sales', email: 'ana@example.com', role: 'sales',
    };

    component.inviteTeamMember();
    http.expectOne('http://localhost:8000/api/v1/company-onboarding/team/members').flush({
      id: 'user-1', first_name: 'Ana', last_name: 'Sales', email: 'ana@example.com',
      role: 'sales', is_active: true, auth_status: 'provisioning_failed',
      invitation_delivery: 'failed', invitation_error_code: 'TOO_MANY_ATTEMPTS_TRY_LATER',
    });
    http.expectOne('http://localhost:8000/api/v1/company-onboarding/team').flush({
      administrator: null, members: [], roles: [], projects: [],
    });
    http.expectOne('http://localhost:8000/api/v1/company-onboarding/chat/state').flush({
      messages: [], profile: EMPTY_COMPANY_PROFILE, sources: [], stage: 'team', version: 1,
      team: { administrator: null, members: [], roles: [] }, next_question: null,
    });
    expect(component.teamError).toContain('TOO_MANY_ATTEMPTS_TRY_LATER');

    component.revokeTeamMember('user-1');
    http.expectOne('http://localhost:8000/api/v1/users/company/user-1/invitation').flush({ detail: 'removed' });
    http.expectOne('http://localhost:8000/api/v1/company-onboarding/team').flush({
      administrator: null, members: [], roles: [], projects: [],
    });
    http.expectOne('http://localhost:8000/api/v1/company-onboarding/chat/state').flush({
      messages: [], profile: EMPTY_COMPANY_PROFILE, sources: [], stage: 'team', version: 2,
      team: { administrator: null, members: [], roles: [] }, next_question: null,
    });
    expect(component.teamSuccess).toContain('email can be invited again');
  });

  it('explains Firebase email quota exhaustion without asking for a duplicate user', () => {
    component.currentStage = 'team';
    component.teamInvite = {
      first_name: 'Ana', last_name: 'Sales', email: 'quota@example.com', role: 'sales',
    };
    const quotaMessage = 'Firebase has exhausted the daily email-link quota. The user was saved, but no invitation was sent.';

    component.inviteTeamMember();
    http.expectOne('http://localhost:8000/api/v1/company-onboarding/team/members').flush({
      id: 'user-quota', first_name: 'Ana', last_name: 'Sales', email: 'quota@example.com',
      role: 'sales', is_active: true, auth_status: 'provisioning_failed',
      invitation_delivery: 'failed', invitation_error_code: 'QUOTA_EXCEEDED',
      invitation_error_message: quotaMessage,
    });
    http.expectOne('http://localhost:8000/api/v1/company-onboarding/team').flush({
      administrator: null, members: [], roles: [], projects: [],
    });
    http.expectOne('http://localhost:8000/api/v1/company-onboarding/chat/state').flush({
      messages: [], profile: EMPTY_COMPANY_PROFILE, sources: [], stage: 'team', version: 1,
      team: { administrator: null, members: [], roles: [] }, next_question: null,
    });

    expect(component.teamError).toContain('The user quota@example.com was saved.');
    expect(component.teamError).toContain('daily email-link quota');
    expect(component.teamMemberStatusLabel({ auth_status: 'provisioning_failed', invitation_error_code: 'QUOTA_EXCEEDED' })).toBe('Email quota exceeded');
  });

  it('shows the structured Firebase quota message returned by Resend', () => {
    component.resendTeamMember('user-quota');
    http.expectOne('http://localhost:8000/api/v1/users/company/user-quota/resend-activation').flush({
      detail: {
        code: 'FIREBASE_EMAIL_QUOTA_EXCEEDED',
        message: 'Firebase daily email-link quota is exhausted.',
      },
    }, { status: 429, statusText: 'Too Many Requests' });

    expect(component.teamError).toBe('Firebase daily email-link quota is exhausted.');
  });

  it('should render extracted list proposals without JSON syntax', () => {
    expect(component.formatProposalValue({
      field: 'corporate_social_profiles',
      value: ['https://instagram.com/example', 'https://linkedin.com/company/example'],
    })).toBe('https://instagram.com/example, https://linkedin.com/company/example');
  });

  it('should continue from Team with one state-changing request', () => {
    component.currentStage = 'team';
    component.continueTeamSetup();

    const request = http.expectOne('http://localhost:8000/api/v1/company-onboarding/team/continue');
    expect(request.request.method).toBe('POST');
    request.flush({
      messages: [], profile: EMPTY_COMPANY_PROFILE, sources: [], stage: 'conditional', version: 1,
      team: {
        administrator: null, members: [],
        roles: [
          { role: 'assistant', label: 'Assistant users', status: 'deferred', active_users: 0 },
          { role: 'mkt', label: 'Marketing users', status: 'deferred', active_users: 0 },
          { role: 'sales', label: 'Sales users', status: 'deferred', active_users: 0 },
        ],
      },
      next_question: { field: 'dba', label: 'DBA', prompt: 'DBA?', input_type: 'text', options: [], examples: [], allow_custom: true, minimum_words: null },
    });

    expect(component.currentStage).toBe('conditional');
    expect(component.nextQuestion?.field).toBe('dba');
    expect(component.team.roles.every(role => role.status === 'deferred')).toBe(true);
  });

  it('keeps invited Team members visible after onboarding advances', () => {
    fixture.detectChanges();
    http.expectOne('http://localhost:8000/api/v1/company-onboarding/chat/state').flush({
      messages: [], profile: EMPTY_COMPANY_PROFILE, sources: [], stage: 'conditional', version: 1,
      team: {
        administrator: null,
        members: [{ id: 'user-1', first_name: 'Ana', last_name: 'Sales', email: 'ana@example.com', role: 'sales', is_active: false, auth_status: 'invited' }],
        roles: [{ role: 'sales', label: 'Sales users', status: 'confirmed', active_users: 0, pending_users: 1, failed_users: 0 }],
      },
      next_question: { field: 'dba', label: 'DBA', prompt: 'DBA?', input_type: 'text', options: [], examples: [], allow_custom: true, minimum_words: null },
    });
    fixture.detectChanges();
    const summary = (fixture.nativeElement as HTMLElement).querySelector('[data-testid="saved-team-summary"]');
    expect(summary?.textContent).toContain('Ana Sales');
    expect(summary?.textContent).toContain('Pending activation');
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

  it('validates required Company user fields before enabling Add user', () => {
    component.teamInvite = { first_name: '', last_name: '', email: 'invalid', role: 'sales' };
    expect(component.teamInviteErrorCount).toBe(3);
    expect(component.canInviteTeamMember).toBe(false);

    component.teamInvite = { first_name: 'Ana', last_name: 'Torres', email: 'ana@example.com', role: 'sales' };
    expect(component.teamInviteErrorCount).toBe(0);
    expect(component.canInviteTeamMember).toBe(true);
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
