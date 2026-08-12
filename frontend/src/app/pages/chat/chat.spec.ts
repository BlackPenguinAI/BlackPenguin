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
          label: 'DBA',
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
      messages: [], profile: EMPTY_COMPANY_PROFILE, sources: [], stage: 'conversation', version: 1,
      next_question: {
        field: null, label: 'Final approval', prompt: 'Approve', input_type: 'boolean',
        options: [], examples: [], allow_custom: true, minimum_words: null,
      },
    });
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
