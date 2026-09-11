import { HttpClientTestingModule, HttpTestingController } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActivatedRoute, Router } from '@angular/router';
import { RouterTestingModule } from '@angular/router/testing';

import { ProjectChatComponent } from './project-chat';
import { EMPTY_PROJECT_PROFILE, ProjectPropertyType } from './project-onboarding.models';


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
          useValue: {
            snapshot: {
              paramMap: { get: () => 'project-1' },
              queryParamMap: { get: () => null },
            },
          },
        },
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(ProjectChatComponent);
    component = fixture.componentInstance;
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    for (const request of http.match((candidate) => candidate.url.endsWith('/property-types'))) {
      request.flush({
        items: [], confirmed_count: 0, candidate_count: 0,
        limit: 20, remaining: 20, catalog_complete: false,
      });
    }
    http.verify();
  });

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

  it('updates one proposal in place without reloading the conversation while review remains', () => {
    const first = {
      id: 'proposal-1', field: 'exact_address', label: 'Address', value: 'Lima',
      draftValue: 'Lima', evidence: null, confidence: 'high', status: 'pending' as const,
    };
    const second = {
      id: 'proposal-2', field: 'city', label: 'City', value: 'Lima',
      draftValue: 'Lima', evidence: null, confidence: 'high', status: 'pending' as const,
    };
    const source = {
      id: 'source-1', kind: 'official_website', status: 'ready' as const, name: 'example.com',
      url: 'https://example.com', mime_type: 'text/html', size_bytes: 100, error_message: null,
      message_id: null, download_url: null, is_primary: false, proposals: [first, second],
      created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
    };
    component.projectId = 'project-1';
    component.sources = [source];

    component.decideProposal(source, first, 'confirm');
    http.expectOne('http://localhost:8000/api/v1/projects/project-1/proposals/proposal-1/decision').flush({
      proposal: { ...first, status: 'confirmed' }, profile: EMPTY_PROJECT_PROFILE,
    });

    http.expectNone('http://localhost:8000/api/v1/projects/project-1/chat/state');
    expect(component.sources[0].proposals.map(item => item.status)).toEqual(['confirmed', 'pending']);
  });

  it('shows proposal validation beside the proposal instead of in the global chat error', () => {
    const proposal = {
      id: 'proposal-short', field: 'target_audience', label: 'Target audience',
      value: 'Families and individuals seeking new homes',
      draftValue: 'Families and individuals seeking new homes with community amenities',
      evidence: null, confidence: 'high', status: 'pending' as const,
      validation: { code: 'minimum_words', field: 'target_audience', message: 'Enter at least 8 words.', minimum_words: 8 },
    };
    const source = {
      id: 'source-short', kind: 'official_website', status: 'ready' as const, name: 'example.com',
      url: 'https://example.com', mime_type: 'text/html', size_bytes: 100, error_message: null,
      message_id: null, download_url: null, is_primary: false, proposals: [proposal],
      created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
    };
    component.projectId = 'project-1';
    component.sources = [source];

    component.decideProposal(source, proposal, 'correct');
    http.expectOne('http://localhost:8000/api/v1/projects/project-1/proposals/proposal-short/decision').flush({
      detail: { code: 'minimum_words', field: 'target_audience', message: 'Enter at least 8 words.', minimum_words: 8 },
    }, { status: 422, statusText: 'Unprocessable Entity' });

    expect(component.sources[0].proposals[0].inlineError).toBe('Enter at least 8 words.');
    expect(component.errorMessage).toBe('');
  });

  it('uses an idempotency key and restores server state after a gateway timeout', () => {
    component.projectId = 'project-1';
    component.prompt = 'Modern homes with thoughtful layouts, exceptional services, and convenient access to the city.';

    component.sendMessage();

    const send = http.expectOne('http://localhost:8000/api/v1/projects/project-1/chat');
    const clientMessageId = send.request.body.client_message_id as string;
    expect(clientMessageId).toMatch(/^[0-9a-f-]{36}$/i);
    send.flush('Gateway timeout', { status: 504, statusText: 'Gateway Timeout' });

    http.expectOne('http://localhost:8000/api/v1/projects/project-1/chat/state').flush({
      messages: [{
        id: clientMessageId, sender: 'user', content: component.messages[0]?.content || 'Saved answer',
        created_at: new Date().toISOString(), attachments: [],
      }],
      profile: EMPTY_PROJECT_PROFILE,
      sources: [],
      stage: 'conversation',
      version: 1,
      next_question: {
        field: 'short_description', label: 'Approved short description', prompt: 'Description?',
        input_type: 'long_text', options: [], examples: [], allow_custom: true, minimum_words: 8,
      },
    });

    expect(component.prompt).toBe('');
    expect(component.messages.some((message) => message.id === clientMessageId)).toBe(true);
    expect(component.errorMessage).toContain('saved');
  });

  it('shows deferred project fields as a non-error pending choice', () => {
    expect(component.statusIcon('deferred')).toBe('schedule');
    expect(component.statusClass('deferred')).toBe('text-gray-600');
  });

  it('uses the confirmed profile name instead of the draft placeholder', () => {
    component.profile = { ...EMPTY_PROJECT_PROFILE, project_name: 'Riverstone Homes' };

    expect(component.projectName).toBe('Riverstone Homes');
  });

  it('keeps processing feedback active for background sources', () => {
    component.isAnalyzing = false;
    component.sources = [{
      id: 'source-processing', kind: 'url', status: 'processing', name: 'cbhhomes.com',
      url: 'https://cbhhomes.com', mime_type: null, size_bytes: null, error_message: null,
      message_id: null, download_url: null, is_primary: false, proposals: [],
      created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
    }];

    expect(component.hasProcessingSources).toBe(true);
  });

  it('keeps Project cover selection provisional until confirmation', () => {
    const source = {
      id: 'cover-1', kind: 'image' as const, status: 'ready' as const, name: 'cover.jpg',
      url: null, mime_type: 'image/jpeg', size_bytes: 100, error_message: null,
      message_id: null, download_url: '/cover', is_primary: false, proposals: [],
      created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
    };

    component.selectCoverCandidate(source);

    expect(component.selectedCoverSourceId).toBe('cover-1');
    http.expectNone('http://localhost:8000/api/v1/projects/project-1/sources/cover-1/cover');
  });

  it('keeps website images out of attachment source reviews', () => {
    component.messages = [{ id: 'message-1', sender: 'user', content: 'https://example.com', created_at: new Date(), attachments: [] }];
    component.sources = [{
      id: 'website-image', kind: 'image', status: 'ready', name: 'hero.jpg',
      url: 'https://example.com/hero.jpg', mime_type: 'image/jpeg', size_bytes: 100,
      error_message: null, message_id: 'message-1', download_url: '/hero', is_primary: false,
      proposals: [], created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
    }];

    expect(component.sourcesForMessage('message-1')).toEqual([]);
    expect(component.unlinkedSources).toEqual([]);
  });

  it('keeps ready uploaded images in their chat attachment instead of duplicating them below the chat', () => {
    component.messages = [{ id: 'message-1', sender: 'user', content: 'Attached image', created_at: new Date(), attachments: [] }];
    component.sources = [{
      id: 'uploaded-image', kind: 'image', status: 'ready', name: 'floorplan.png',
      url: null, mime_type: 'image/png', size_bytes: 100, error_message: null,
      message_id: 'message-1', download_url: '/floorplan', is_primary: false,
      proposals: [], created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
    }];

    expect(component.sourcesForMessage('message-1')).toEqual([]);
    expect(component.unlinkedSources).toEqual([]);
    expect(component.readyProjectImages).toHaveLength(1);
  });

  it('formats structured extraction values without raw JSON', () => {
    expect(component.formatProposalValue({
      field: 'location', value: { city: 'Lima', coordinates: { latitude: -12.04, longitude: -77.03 } },
    })).toBe('City: Lima\nCoordinates › Latitude: -12.04\nCoordinates › Longitude: -77.03');
  });

  it('shows the cover step even when no scraped image is available', () => {
    component.nextQuestion = {
      field: 'project_cover', label: 'Project cover', prompt: 'Choose cover',
      input_type: 'project_cover', options: [], examples: [], allow_custom: false, minimum_words: null,
    };
    component.sources = [];

    expect(component.showCoverPicker).toBe(true);
  });

  it('keeps a saved cover transition visible while the catalog form becomes active', () => {
    const message = {
      id: 'cover-confirmation', sender: 'ai' as const,
      content: 'I saved harbor-hero.jpg as the Project cover image.\n\nLet\'s continue: Review the catalog.',
      created_at: new Date(), attachments: [], response_payload: null,
      ui_payload: {
        field: 'property_type_catalog', label: 'Property catalog', prompt: 'Review the catalog',
        input_type: 'property_type_catalog', options: [], examples: [], allow_custom: false,
        minimum_words: null,
      },
    };

    expect(component.isGlobalStructuredQuestion(message)).toBe(true);
    expect(component.hasPersistedStructuredTransition(message)).toBe(true);
  });

  it('saves only the selected property type and maps server validation to its fields', () => {
    const propertyType: ProjectPropertyType = {
      id: 'type-2', project_id: 'project-1', name: 'Four bedrooms', code: null, description: null,
      bedrooms: 4, bathrooms: 3.5, area_min: null, area_max: null, area_unit: 'ft²',
      total_units: 1, available_units: 1, starting_price: 10, maximum_price: 20,
      currency: 'USD', features: [], inventory_updated_at: '2026-08-01', images_status: 'pending',
      review_status: 'candidate', source_reference: null, sort_order: 1, is_complete: false,
      media: [], created_at: '2026-08-01T00:00:00Z', updated_at: '2026-08-01T00:00:00Z',
    };
    component.projectId = 'project-1';
    component.propertyCatalog.items = [propertyType];

    component.confirmPropertyType(propertyType);

    expect(component.isPropertyTypeSaving(propertyType)).toBe(true);
    const request = http.expectOne('http://localhost:8000/api/v1/projects/project-1/property-types/type-2');
    expect(request.request.body).not.toHaveProperty('id');
    expect(request.request.body).not.toHaveProperty('project_id');
    expect(request.request.body).not.toHaveProperty('media');
    expect(request.request.body.inventory_updated_at).toBe('2026-08-01T12:00:00.000Z');
    request.flush({
      detail: {
        code: 'incomplete_property_type', message: 'Review the highlighted fields.',
        field_errors: { inventory_updated_at: 'Select the inventory update date.' },
      },
    }, { status: 422, statusText: 'Unprocessable Entity' });

    expect(component.isPropertyTypeSaving(propertyType)).toBe(false);
    expect(component.propertyTypeError(propertyType, 'inventory_updated_at')).toContain('inventory update date');
    expect(component.errorMessage).toBe('');
  });

  it('removes an extracted property suggestion and refreshes the active catalog step', () => {
    const propertyType: ProjectPropertyType = {
      id: 'type-candidate', project_id: 'project-1', name: 'Bayside Collection', code: null, description: null,
      bedrooms: null, bathrooms: null, area_min: null, area_max: null, area_unit: null,
      total_units: null, available_units: null, starting_price: null, maximum_price: null,
      currency: null, features: [], inventory_updated_at: null, images_status: 'pending',
      review_status: 'candidate', source_reference: 'https://example.com', sort_order: 0, is_complete: false,
      media: [], created_at: '2026-09-01T00:00:00Z', updated_at: '2026-09-01T00:00:00Z',
    };
    component.projectId = 'project-1';
    component.propertyCatalog = {
      items: [propertyType], confirmed_count: 0, candidate_count: 1,
      limit: 20, remaining: 20, catalog_complete: false,
    };

    component.rejectPropertyType(propertyType);

    expect(component.removingPropertyTypeIds.has(propertyType.id)).toBe(true);
    http.expectOne('http://localhost:8000/api/v1/projects/project-1/property-types/type-candidate')
      .flush(null, { status: 204, statusText: 'No Content' });
    expect(component.propertyCatalog.items).toEqual([]);
    expect(component.propertyCatalog.candidate_count).toBe(0);

    http.expectOne('http://localhost:8000/api/v1/projects/project-1/chat/state').flush({
      messages: [], profile: EMPTY_PROJECT_PROFILE, sources: [], stage: 'conversation', version: 1,
      next_question: {
        field: 'property_type_catalog', label: 'Property catalog', prompt: 'Review catalog',
        input_type: 'property_type_catalog', options: [], examples: [], allow_custom: false, minimum_words: null,
      },
    });
    http.expectOne('http://localhost:8000/api/v1/projects/project-1/property-types').flush({
      items: [], confirmed_count: 0, candidate_count: 0,
      limit: 20, remaining: 20, catalog_complete: false,
    });
    expect(component.removingPropertyTypeIds.has(propertyType.id)).toBe(false);
  });

  it('shows a useful error when a property suggestion cannot be removed', () => {
    const propertyType = { id: 'type-candidate', review_status: 'candidate' } as ProjectPropertyType;
    component.projectId = 'project-1';

    component.rejectPropertyType(propertyType);
    http.expectOne('http://localhost:8000/api/v1/projects/project-1/property-types/type-candidate').flush({
      detail: { message: 'The catalog changed. Refresh and try again.' },
    }, { status: 409, statusText: 'Conflict' });

    expect(component.errorMessage).toBe('The catalog changed. Refresh and try again.');
    expect(component.removingPropertyTypeIds.has(propertyType.id)).toBe(false);
  });

  it('keeps an empty Property catalog explicit until the user chooses to add a type', () => {
    component.propertyCatalog = {
      items: [], confirmed_count: 0, candidate_count: 0,
      limit: 30, remaining: 30, catalog_complete: false,
    };

    expect(component.showPropertyTypeForm).toBe(false);
    expect(component.propertyCatalog.items).toEqual([]);
  });

  it('attaches images selected before saving the first property type', () => {
    const created: ProjectPropertyType = {
      id: 'type-new', project_id: 'project-1', name: 'Typology 1', code: null, description: null,
      bedrooms: null, bathrooms: null, area_min: null, area_max: null, area_unit: 'm²',
      total_units: 10, available_units: 10, starting_price: 50000, maximum_price: 60000,
      currency: 'USD', features: [], inventory_updated_at: '2026-09-06', images_status: 'pending',
      review_status: 'confirmed', source_reference: null, sort_order: 0, is_complete: true,
      media: [], created_at: '2026-09-06T00:00:00Z', updated_at: '2026-09-06T00:00:00Z',
    };
    component.projectId = 'project-1';
    component.showPropertyTypeForm = true;
    component.propertyTypeDraft = {
      name: 'Typology 1', total_units: 10, available_units: 10,
      starting_price: 50000, maximum_price: 60000, currency: 'USD',
      area_unit: 'm²', inventory_updated_at: '2026-09-06',
    };
    component.toggleDraftPropertyTypeImage('image-1');
    component.toggleDraftPropertyTypeImage('image-2');

    component.saveNewPropertyType();

    const create = http.expectOne('http://localhost:8000/api/v1/projects/project-1/property-types');
    expect(create.request.method).toBe('POST');
    create.flush(created);
    const attach = http.expectOne('http://localhost:8000/api/v1/projects/project-1/property-types/type-new/media');
    expect(attach.request.body).toEqual({ source_ids: ['image-1', 'image-2'] });
    attach.flush({
      ...created, images_status: 'provided',
      media: [
        { id: 'media-1', source_id: 'image-1', caption: null, sort_order: 0, image_url: '/image-1' },
        { id: 'media-2', source_id: 'image-2', caption: null, sort_order: 1, image_url: '/image-2' },
      ],
    });

    expect(component.showPropertyTypeForm).toBe(false);
    expect(component.propertyTypeDraftImageSelection.size).toBe(0);
    expect(component.propertyCatalog.items[0].media).toHaveLength(2);
    http.expectOne('http://localhost:8000/api/v1/projects/project-1/chat/state').flush({
      messages: [], profile: EMPTY_PROJECT_PROFILE, sources: [], stage: 'conversation', version: 1,
      next_question: {
        field: 'property_type_catalog', label: 'Property catalog', prompt: 'Review catalog',
        input_type: 'property_type_catalog', options: [], examples: [], allow_custom: false, minimum_words: null,
      },
    });
  });

  it('keeps operational routing and Meta sections out of the Project Profile list', () => {
    component.profile = {
      ...EMPTY_PROJECT_PROFILE,
      fields: [
        { key: 'project_name', label: 'Project name', section: 'identity', requirement: 'required', status: 'missing', applicable: true },
        { key: 'sales_contacts', label: 'Assigned Sales team', section: 'routing', requirement: 'required', status: 'missing', applicable: true },
        { key: 'campaigns_defined', label: 'Meta Lead Ads setup', section: 'campaigns', requirement: 'required', status: 'missing', applicable: true },
      ],
      completion: {
        ...EMPTY_PROJECT_PROFILE.completion,
        sections: [
          { key: 'identity', label: 'Project Identity', completed: 0, total: 1, percentage: 0 },
          { key: 'routing', label: 'Team & Routing', completed: 0, total: 2, percentage: 0 },
          { key: 'campaigns', label: 'Campaigns & Meta', completed: 0, total: 2, percentage: 0 },
        ],
      },
    };

    expect(component.profileSections.map((section) => section.key)).toEqual(['identity']);
  });

  it('finishes a Sales invitation immediately and keeps a fresh form pristine', () => {
    component.projectId = 'project-1';
    component.salesInvite = { first_name: 'Jorge', last_name: 'Jorgei', email: 'jorge@example.com' };
    component.salesInviteTouched = true;

    component.inviteSalesUser({ id: 'team-question', sender: 'ai', content: 'Assign team', created_at: new Date(), attachments: [] });
    expect(component.teamBusy).toBe(true);
    http.expectOne('http://localhost:8000/api/v1/projects/project-1/team/invite-sales').flush({
      id: 'assignment-1', project_id: 'project-1', user_id: 'user-1', responsibility: 'sales',
      is_primary: false, routing_weight: 100, accepts_new_leads: true, is_active: true,
      email: 'jorge@example.com', first_name: 'Jorge', last_name: 'Jorgei',
      invitation_id: 'invitation-1', invitation_status: 'accepted_by_provider', delivery_status: 'accepted',
      invitation_message: 'The activation email was accepted by the provider.',
    });

    expect(component.teamBusy).toBe(false);
    expect(component.showSalesInviteForm).toBe(false);
    expect(component.salesInviteTouched).toBe(false);
    expect(component.salesInviteErrorCount).toBe(3);
    expect(component.teamSetupMessage).toContain('activation email was accepted');
    expect(component.projectTeam.map(item => item.user_id)).toEqual(['user-1']);
  });

  it('renders the structured duplicate-email conflict instead of object Object', () => {
    component.projectId = 'project-1';
    component.salesInvite = { first_name: 'Jorge', last_name: 'Jesus', email: 'jorge@example.com' };

    component.inviteSalesUser({ id: 'team-question', sender: 'ai', content: 'Assign team', created_at: new Date(), attachments: [] });
    http.expectOne('http://localhost:8000/api/v1/projects/project-1/team/invite-sales').flush({
      detail: {
        code: 'USER_ALREADY_INVITED', message: 'This user is already pending activation.',
        user_id: 'user-1', auth_status: 'invited', next_action: 'resend_activation',
      },
    }, { status: 409, statusText: 'Conflict' });

    expect(component.errorMessage).toBe('This user is already pending activation. Resend the activation invitation from Users.');
    expect(component.errorMessage).not.toContain('[object Object]');
    expect(component.salesInvite.email).toBe('jorge@example.com');
  });

  it('restores the conversation bottom after returning from Meta OAuth', () => {
    const route = TestBed.inject(ActivatedRoute) as unknown as {
      snapshot: { queryParamMap: { get(key: string): string | null } };
    };
    route.snapshot.queryParamMap.get = (key: string) => key === 'meta_oauth' ? 'connected' : null;
    const syncState = vi.spyOn(component as unknown as { syncState(mode?: string): void }, 'syncState').mockImplementation(() => undefined);
    vi.spyOn(component, 'loadCampaigns').mockImplementation(() => undefined);
    vi.spyOn(component, 'loadMetaConnections').mockImplementation(() => undefined);
    vi.spyOn(component, 'loadSalesTeam').mockImplementation(() => undefined);
    vi.spyOn(component, 'loadMetaSetupConfiguration').mockImplementation(() => undefined);
    const navigate = vi.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);

    component.ngOnInit();

    expect(syncState).toHaveBeenCalledWith('bottom');
    expect(component.metaSetupMessage).toContain('Meta connected');
    expect(navigate).toHaveBeenCalledWith([], expect.objectContaining({ replaceUrl: true }));
  });

  it('cascades Meta Campaign, Ad Set and Ad options and selects the Ad Lead Form', () => {
    component.metaAssets = {
      authorizations: [], pages: [], ad_accounts: [], warnings: [],
      campaigns: [
        { id: 'campaign-1', name: 'Lead campaign', status: 'ACTIVE', objective: 'OUTCOME_LEADS' },
        { id: 'campaign-2', name: 'Other campaign', status: 'ACTIVE' },
      ],
      adsets: [
        { id: 'adset-1', name: 'First Ad Set', status: 'ACTIVE', parent_id: 'campaign-1' },
        { id: 'adset-2', name: 'Other Ad Set', status: 'ACTIVE', parent_id: 'campaign-2' },
      ],
      ads: [
        { id: 'ad-1', name: 'Lead Ad', status: 'ACTIVE', parent_id: 'adset-1', lead_form_id: 'form-1' },
        { id: 'ad-2', name: 'Other Ad', status: 'ACTIVE', parent_id: 'adset-2', lead_form_id: 'form-2' },
      ],
      lead_forms: [
        { id: 'form-1', name: 'Project form', status: 'ACTIVE' },
        { id: 'form-2', name: 'Other form', status: 'ACTIVE' },
      ],
    };
    component.metaOAuth.external_campaign_id = 'campaign-1';

    expect(component.metaAdSetOptions.map(item => item.id)).toEqual(['adset-1']);
    component.metaOAuth.external_adset_id = 'adset-1';
    expect(component.metaAdOptions.map(item => item.id)).toEqual(['ad-1']);
    component.metaOAuth.external_ad_id = 'ad-1';
    component.metaAdChanged();

    expect(component.metaOAuth.lead_form_id).toBe('form-1');
    expect(component.metaLeadFormOptions.map(item => item.id)).toEqual(['form-1']);
  });

  it('clears dependent Meta selections when a parent selection changes', () => {
    component.metaOAuth.external_campaign_id = 'campaign-1';
    component.metaOAuth.external_adset_id = 'adset-1';
    component.metaOAuth.external_ad_id = 'ad-1';
    component.metaOAuth.lead_form_id = 'form-1';

    component.metaCampaignChanged();

    expect(component.metaOAuth.external_campaign_id).toBe('campaign-1');
    expect(component.metaOAuth.external_adset_id).toBe('');
    expect(component.metaOAuth.external_ad_id).toBe('');
    expect(component.metaOAuth.lead_form_id).toBe('');
  });

  it('keeps Meta manual setup collapsed and exposes the OAuth blocker', () => {
    component.metaSetupConfig = {
      partner_business_manager_id: null, configured: false, oauth_enabled: false,
      oauth_status: 'pending_verification', oauth_blocker_code: 'META_OAUTH_NOT_VERIFIED',
      oauth_blocker_message: 'The Meta App credentials must be verified.', can_connect: false,
      manual_fallback_enabled: true,
    };
    component.showManualMetaSetup = false;

    expect(component.metaSetupConfig.oauth_enabled).toBe(false);
    expect(component.metaSetupConfig.oauth_blocker_code).toBe('META_OAUTH_NOT_VERIFIED');
    expect(component.showManualMetaSetup).toBe(false);
  });
});
