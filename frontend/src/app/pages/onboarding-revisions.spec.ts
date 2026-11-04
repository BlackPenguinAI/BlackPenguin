import { TestBed } from '@angular/core/testing';
import { ActivatedRoute, provideRouter } from '@angular/router';
import { TranslateModule } from '@ngx-translate/core';
import { of } from 'rxjs';
import { afterEach, describe, expect, it } from 'vitest';
import { ChatComponent } from './chat/chat';
import { CompanyOnboardingService } from './chat/company-onboarding.service';
import { EMPTY_COMPANY_PROFILE } from './chat/company-onboarding.models';
import { ProjectChatComponent } from './client/projects/project-chat/project-chat';
import { ProjectOnboardingService } from './client/projects/project-chat/project-onboarding.service';
import { EMPTY_PROJECT_PROFILE } from './client/projects/project-chat/project-onboarding.models';

describe('Published and draft onboarding UI', () => {
  afterEach(() => TestBed.resetTestingModule());

  it('keeps the Company composer and explains what is still published', async () => {
    const profile = { ...EMPTY_COMPANY_PROFILE, completion: {
      ...EMPTY_COMPANY_PROFILE.completion, has_pending_changes: true,
      active_profile_approved: true, final_approved: false,
    } };
    await TestBed.configureTestingModule({
      imports: [ChatComponent, TranslateModule.forRoot()],
      providers: [provideRouter([]), { provide: CompanyOnboardingService, useValue: {
        getState: () => of({ profile, messages: [], sources: [], next_question: null,
          stage: 'approval', version: 1, team: { administrator: null, members: [], roles: [] } }),
        getMedia: () => of([]),
      } }],
    }).compileComponents();
    const fixture = TestBed.createComponent(ChatComponent);
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('previously approved Company Profile remains active');
    expect(fixture.nativeElement.querySelector('textarea')).not.toBeNull();
  });

  it('shows a pending Project revision separately from channel readiness', async () => {
    const profile = { ...EMPTY_PROJECT_PROFILE, completion: {
      ...EMPTY_PROJECT_PROFILE.completion, has_pending_changes: true,
      active_profile_approved: true, final_approved: false,
      capabilities: {
        manual_messaging: { ready: true, blockers: [] },
        meta_lead_ads: { ready: false, blockers: [{ field: 'campaigns_defined', label: 'Meta setup', status: 'deferred' }] },
      },
    } };
    const empty = () => of([]);
    await TestBed.configureTestingModule({
      imports: [ProjectChatComponent], providers: [provideRouter([]),
        { provide: ActivatedRoute, useValue: { snapshot: { paramMap: { get: () => 'project-1' }, queryParamMap: { get: () => null } } } },
        { provide: ProjectOnboardingService, useValue: {
          getState: () => of({ profile, messages: [], sources: [], next_question: null, stage: 'approval', version: 1 }),
          getPropertyTypes: () => of({ items: [], confirmed_count: 0, candidate_count: 0, limit: 20, remaining: 20, catalog_complete: false }),
          getMetaSetupConfiguration: () => of({ configured: false, oauth_enabled: false, blockers: [] }),
          getMetaSetupState: () => of({ project_id: 'project-1', account_status: 'not_connected', routing_status: 'not_linked', authorizations: [], missing_permissions: [], mappings: [] }),
          getSalesAssets: empty, getCampaigns: empty, getMetaConnections: empty,
          getProjectTeam: empty, getSalesCandidates: empty,
        } },
      ],
    }).compileComponents();
    const fixture = TestBed.createComponent(ProjectChatComponent);
    fixture.detectChanges();
    const text = fixture.nativeElement.textContent;
    expect(text).toContain('Leads continue using the previously approved Project version');
    expect(text).toContain('manual messaging: Ready');
    expect(text).toContain('meta lead ads: Pending');
    expect(text).toContain('Meta setup: deferred');
  });
});
