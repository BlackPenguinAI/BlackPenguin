import { HttpClientTestingModule, HttpTestingController } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActivatedRoute } from '@angular/router';
import { RouterTestingModule } from '@angular/router/testing';

import { ProjectChatComponent } from './project-chat';
import { EMPTY_PROJECT_PROFILE } from './project-onboarding.models';


describe('ProjectChatComponent', () => {
  let component: ProjectChatComponent;
  let fixture: ComponentFixture<ProjectChatComponent>;
  let http: HttpTestingController;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [ProjectChatComponent, HttpClientTestingModule, RouterTestingModule],
      providers: [
        {
          provide: ActivatedRoute,
          useValue: { snapshot: { paramMap: { get: () => 'project-1' } } },
        },
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(ProjectChatComponent);
    component = fixture.componentInstance;
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('should wait for state before showing onboarding UI', () => {
    expect(component.initialState).toBe('loading');
    expect(component.showWelcome).toBe(false);
  });

  it('should keep project source review inline and block later questions until resolved', () => {
    component.messages = [
      { id: 'message-1', sender: 'user', content: 'project.pdf', created_at: new Date(), attachments: [] },
      {
        id: 'question-1', sender: 'ai', content: 'Next question', created_at: new Date(), attachments: [],
        ui_payload: { field: 'address', label: 'Address', prompt: 'Next question', input_type: 'text', options: [], examples: [], allow_custom: true, minimum_words: null },
      },
    ];
    component.sources = [{
      id: 'source-1', kind: 'uploaded_file', status: 'ready', name: 'project.pdf',
      url: null, mime_type: 'application/pdf', size_bytes: 100, error_message: null,
      message_id: 'message-1', download_url: '/file', is_primary: false,
      proposals: [{ id: 'proposal-1', field: 'exact_address', label: 'Address', value: 'Lima', evidence: null, confidence: 'high', status: 'pending' }],
      created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
    }];
    component.prompt = 'Should not send';

    expect(component.sourcesForMessage('message-1').map((source) => source.id)).toEqual(['source-1']);
    expect(component.unlinkedSources).toEqual([]);
    expect(component.visibleMessages.map((message) => message.id)).toEqual(['message-1']);
    expect(component.isSourceExpanded(component.sources[0])).toBe(true);
    expect(component.canSend).toBe(false);
  });

  it('expands a failed uploaded file without treating it as pending review', () => {
    const source = {
      id: 'source-failed', kind: 'uploaded_file' as const, status: 'failed' as const,
      name: 'protected.pdf', url: null, mime_type: 'application/pdf', size_bytes: 100,
      error_message: "I couldn't analyze this file because it is password-protected.",
      message_id: 'message-1', download_url: '/file', is_primary: false, proposals: [],
      created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
    };
    component.sources = [source];
    component.prompt = 'Continue manually';

    expect(component.isSourceExpanded(source)).toBe(true);
    expect(component.hasPendingReview).toBe(false);
    expect(component.canSend).toBe(true);
  });

  it('should preserve review position and keep the source expanded after the last decision', () => {
    const proposal = {
      id: 'proposal-last', field: 'exact_address', label: 'Address', value: 'Lima',
      draftValue: 'Lima', evidence: null, confidence: 'high', status: 'pending' as const,
    };
    const source = {
      id: 'source-last', kind: 'official_website', status: 'ready' as const, name: 'example.com',
      url: 'https://example.com', mime_type: 'text/html', size_bytes: 100, error_message: null,
      message_id: null, download_url: null, is_primary: false, proposals: [proposal],
      created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
    };
    component.projectId = 'project-1';
    component.sources = [source];
    (component as unknown as { expandedSourceIds: Set<string> }).expandedSourceIds.add(source.id);
    const scrollToBottom = vi.spyOn(component as unknown as { scrollToBottom(): void }, 'scrollToBottom');

    component.decideProposal(source, proposal, 'confirm');
    http.expectOne('http://localhost:8000/api/v1/projects/project-1/proposals/proposal-last/decision').flush({
      proposal: { ...proposal, status: 'confirmed' }, profile: EMPTY_PROJECT_PROFILE,
    });
    http.expectOne('http://localhost:8000/api/v1/projects/project-1/chat/state').flush({
      messages: [], profile: EMPTY_PROJECT_PROFILE,
      sources: [{ ...source, proposals: [{ ...proposal, status: 'confirmed' }] }],
      stage: 'conversation', version: 1,
      next_question: { field: 'project_type', label: 'Project type', prompt: 'Project type?', input_type: 'text', options: [], examples: [], allow_custom: true, minimum_words: null },
    });

    expect(scrollToBottom).not.toHaveBeenCalled();
    expect(component.sources[0].proposals[0].status).toBe('confirmed');
    expect(component.isSourceExpanded(component.sources[0])).toBe(true);
  });
});
