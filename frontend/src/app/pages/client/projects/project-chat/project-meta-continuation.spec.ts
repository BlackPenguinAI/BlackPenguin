import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActivatedRoute, provideRouter, Router } from '@angular/router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ProjectChatComponent } from './project-chat';
import { EMPTY_PROJECT_PROFILE, ChatMessage } from './project-onboarding.models';

const initialize=ProjectChatComponent.prototype.ngOnInit;
const authorization={id:'auth-1',meta_user_id:'private-meta-id',meta_user_name:'Jorge Ktch',status:'active',scopes:[],expires_at:null,created_at:''};
const saved={project_id:'project-1',account_status:'connected',routing_status:'not_linked',missing_permissions:[],mappings:[],authorizations:[authorization],last_authorization:authorization};
const question={field:'campaigns_defined',task:'meta_account',label:'Meta Lead Ads setup',prompt:'Configure Meta',input_type:'meta_lead_setup',options:[],examples:[],allow_custom:false,minimum_words:null};

describe('Verified Meta continuation', () => {
  let fixture: ComponentFixture<ProjectChatComponent>,c:ProjectChatComponent,http:HttpTestingController;
  beforeEach(async()=>{
    vi.spyOn(ProjectChatComponent.prototype,'ngOnInit').mockImplementation(()=>undefined);
    await TestBed.configureTestingModule({imports:[ProjectChatComponent],providers:[provideHttpClient(),provideHttpClientTesting(),provideRouter([]),{provide:ActivatedRoute,useValue:{snapshot:{paramMap:{get:()=> 'project-1'},queryParamMap:{get:()=>null}}}}]}).compileComponents();
    fixture=TestBed.createComponent(ProjectChatComponent);c=fixture.componentInstance;http=TestBed.inject(HttpTestingController);
    c.projectId='project-1';c.initialState='ready';c.showWelcome=false;c.metaSetupConfig={...c.metaSetupConfig,oauth_enabled:true};
    c.profile=EMPTY_PROJECT_PROFILE;c.nextQuestion=question as never;
    c.messages=[{id:'question',sender:'ai',content:'Configure Meta',attachments:[],created_at:'2026-11-01T00:00:00Z',ui_payload:question} as unknown as ChatMessage];
    vi.spyOn(c,'loadMetaAssets').mockImplementation(()=>undefined);
  });
  afterEach(()=>{http.verify();TestBed.resetTestingModule();});

  it('shows the server account identity once in the collapsed account step, opens campaigns and performs no association',()=>{
    c.loadMetaSetupState();http.expectOne(r=>r.url.includes('/meta/setup-state')).flush(saved);fixture.detectChanges();
    const root=fixture.nativeElement as HTMLElement;
    const account=root.querySelector('[data-testid=meta-account-step]')!;
    const campaigns=root.querySelector('[data-testid=meta-project-step]')!;
    expect(account.querySelector('button')!.getAttribute('aria-expanded')).toBe('false');
    expect(campaigns.querySelector('button')!.getAttribute('aria-expanded')).toBe('true');
    expect(account.querySelector('button')!.textContent).toContain('Jorge Ktch');
    expect(root.querySelector('img[alt="Meta"]')).toBeTruthy();
    expect(root.textContent?.match(/Step 1 · Account and permissions/g)).toHaveLength(1);
    expect(root.textContent?.match(/Step 2 · Project campaign and form/g)).toHaveLength(1);
    expect(root.textContent).not.toContain('Continue to project campaigns');
    expect(root.textContent).not.toContain('private-meta-id');
    expect(campaigns.querySelector('[data-testid=meta-campaign-deferral]')).toBeTruthy();
    expect(c.metaOAuth.authorization_id).toBe('auth-1');expect(c.loadMetaAssets).toHaveBeenCalledOnce();
    http.expectNone(r=>r.method==='POST');
  });

  it('does not override a user reopening account review and retains unsaved campaign selections',()=>{
    c.metaOAuth.page_id='unsaved-page';c.setMetaReviewStep('account');
    c.loadMetaSetupState();http.expectOne(r=>r.url.includes('/meta/setup-state')).flush(saved);
    expect(c.metaReviewStep).toBe('account');expect(c.metaOAuth.page_id).toBe('unsaved-page');
    expect(c.loadMetaAssets).not.toHaveBeenCalled();
  });

  it('does not claim OAuth success or advance when saved permissions are incomplete',()=>{
    (c as any).metaReturnPending=true;c.metaSetupMessage='Checking your saved Meta connection…';
    c.loadMetaSetupState();http.expectOne(r=>r.url.includes('/meta/setup-state')).flush({...saved,account_status:'permissions_required',missing_permissions:['leads_retrieval']});
    expect(c.metaReviewStep).toBe('account');expect(c.showMetaAssetStep).toBe(false);
    expect(c.metaSetupMessage).toBe('');expect(c.metaStateError).toContain('needs attention');
    expect(c.loadMetaAssets).not.toHaveBeenCalled();http.expectNone(r=>r.method==='POST');
  });

  it('allows a failed saved-status lookup to be retried without losing form selections',()=>{
    c.metaOAuth.page_id='keep';(c as any).metaReturnPending=true;
    c.loadMetaSetupState();http.expectOne(r=>r.url.includes('/meta/setup-state')).flush({}, {status:503,statusText:'Unavailable'});
    expect(c.metaSetupMessage).toBe('');expect(c.metaStateError).toContain('Refresh');
    c.loadMetaSetupState();http.expectOne(r=>r.url.includes('/meta/setup-state')).flush(saved);
    expect(c.metaReviewStep).toBe('assets');expect(c.metaOAuth.page_id).toBe('keep');expect(c.metaStateError).toBe('');
  });

  it('restores drafts after an OAuth cancellation without claiming success or advancing',()=>{
    for(const method of ['syncState','loadCampaigns','loadMetaConnections','loadSalesTeam','loadMetaSetupConfiguration'] as const)
      vi.spyOn(c as any,method).mockImplementation(()=>undefined);
    const route=TestBed.inject(ActivatedRoute) as any;
    route.snapshot.queryParamMap.get=(key:string)=>key==='meta_oauth'?'error':key==='reason'?'Meta authorization cancelled.':null;
    vi.spyOn(TestBed.inject(Router),'navigate').mockResolvedValue(true);
    sessionStorage.setItem('bp-meta-draft:project-1',JSON.stringify({prompt:'Keep my question',metaOAuth:{authorization_id:'auth-1',page_id:'draft-page',campaign_name:'Draft campaign'}}));
    initialize.call(c);
    http.expectOne(r=>r.url.includes('/meta/setup-state')).flush(saved);
    expect(c.metaReviewStep).toBe('account');expect(c.showMetaAssetStep).toBe(false);
    expect(c.errorMessage).toContain('cancelled');expect(c.metaSetupMessage).not.toContain('Meta connected');
    expect(c.prompt).toBe('Keep my question');expect(c.metaOAuth.page_id).toBe('draft-page');
    expect(c.loadMetaAssets).not.toHaveBeenCalled();http.expectNone(r=>r.method==='POST');
  });

  it('ignores an older authorization list after authoritative setup status confirms the account',()=>{
    c.loadMetaAuthorizations();const older=http.expectOne(r=>r.url.endsWith('/meta/oauth/authorizations'));
    c.loadMetaSetupState();http.expectOne(r=>r.url.includes('/meta/setup-state')).flush(saved);
    older.flush([]);
    expect(c.metaOAuth.authorization_id).toBe('auth-1');expect(c.metaAccountName).toBe('Jorge Ktch');
  });
});
