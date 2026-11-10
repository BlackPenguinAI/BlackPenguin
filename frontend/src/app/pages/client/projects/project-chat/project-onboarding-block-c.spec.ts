import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { ProjectChatComponent } from './project-chat';
import { EMPTY_PROJECT_PROFILE, ChatMessage, ProjectSource } from './project-onboarding.models';

const initialize = ProjectChatComponent.prototype.ngOnInit;
const payload = {field:'campaigns_defined',label:'Meta Lead Ads setup',input_type:'meta_lead_setup',prompt:'Configure Meta',options:[],examples:[],allow_custom:false,minimum_words:null};
const message = () => ({id:'meta-question',sender:'ai',content:'Configure Meta',created_at:new Date(),attachments:[],ui_payload:payload} as ChatMessage);
const saved = {project_id:'project-1',account_status:'connected',routing_status:'not_linked',missing_permissions:[],mappings:[]};

describe('Project onboarding Block C interface regression', () => {
  let fixture: ComponentFixture<ProjectChatComponent>;
  let c: ProjectChatComponent;
  let http: HttpTestingController;
  beforeEach(async () => {
    vi.spyOn(ProjectChatComponent.prototype,'ngOnInit').mockImplementation(() => undefined);
    await TestBed.configureTestingModule({imports:[ProjectChatComponent],providers:[provideHttpClient(),provideHttpClientTesting(),provideRouter([])]}).compileComponents();
    fixture = TestBed.createComponent(ProjectChatComponent); c = fixture.componentInstance;
    c.projectId='project-1';c.initialState='ready';c.showWelcome=false;
    c.metaAccountState={...saved} as never;
    http=TestBed.inject(HttpTestingController);
  });
  afterEach(() => {vi.useRealTimers();http.verify();TestBed.resetTestingModule();});
  const meta = () => { c.messages=[message()]; c.nextQuestion=payload; fixture.detectChanges(); };
  const disclosure = (step:string) => fixture.nativeElement.querySelector(`[data-testid="${step}"] app-review-card button[aria-expanded]`) as HTMLButtonElement;

  it('renders a single set of task shortcuts in the responsive review panel', () => {
    fixture.detectChanges();
    const navs=fixture.nativeElement.querySelectorAll('nav[aria-label="Project review tasks"]');
    expect(navs.length).toBe(1);
    expect(fixture.nativeElement.querySelector('nav[aria-label="Edit Project onboarding"]')).toBeNull();
    expect(navs[0].querySelectorAll('button').length).toBe(9);
    expect(navs[0].closest('#project-review-panel')).toBeTruthy();
  });

  it('keeps Meta summaries and source deferral buttons out of URL processing', () => {
    c.onboardingStage='processing';
    c.sources=[{id:'web',kind:'url',status:'processing',name:'example.com',url:'https://example.com',proposals:[]} as unknown as ProjectSource];
    c.messages=[{id:'url',sender:'user',content:'https://example.com',attachments:[],created_at:new Date()}];
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('[data-testid="meta-saved-summary"]')).toBeNull();
    expect(fixture.nativeElement.querySelector('.processing-source')).toBeTruthy();
    expect(fixture.nativeElement.querySelectorAll('app-configure-later').length).toBe(0);
    const buttons=fixture.nativeElement.querySelectorAll('nav[aria-label="Project review tasks"] button');
    expect([...buttons].every(button => (button as HTMLButtonElement).disabled)).toBe(true);
  });

  it('places source deferral inside the identified source review card after processing', () => {
    c.sources=[{id:'web',kind:'url',status:'ready',name:'example.com',url:'https://example.com',proposals:[]} as unknown as ProjectSource];
    fixture.detectChanges();
    const defer=fixture.nativeElement.querySelector('details.source-review app-configure-later');
    expect(defer).toBeTruthy();
    expect(defer.textContent).toContain('Review example.com later');
    expect(fixture.nativeElement.querySelector('.processing-source')).toBeNull();
  });

  it('starts with account review expanded even when Company authorization is saved', () => {
    meta();
    expect(disclosure('meta-account-step').getAttribute('aria-expanded')).toBe('true');
    expect(disclosure('meta-project-step').getAttribute('aria-expanded')).toBe('false');
    const summary=fixture.nativeElement.querySelector('[data-testid="meta-saved-summary"]');
    expect(summary).toBeNull();
    expect(fixture.nativeElement.querySelector('[data-testid=meta-account-status]').textContent).toContain('Company level');
    http.expectNone(request => request.method === 'POST');
  });

  it('opens campaigns when a connected saved account is verified asynchronously', () => {
    c.metaAccountState=null;meta();
    c.loadMetaSetupState();
    http.expectOne(request => request.url.includes('/meta/setup-state')).flush(saved);
    fixture.detectChanges();
    expect(disclosure('meta-account-step').getAttribute('aria-expanded')).toBe('false');
    expect(disclosure('meta-project-step').getAttribute('aria-expanded')).toBe('true');
  });

  it('opens step 2 only on explicit continuation and preserves the selected assets when switching', () => {
    const discover=vi.spyOn(c,'loadMetaAssets').mockImplementation(() => undefined);
    c.metaOAuth.authorization_id='auth-1';c.metaOAuth.page_id='page-to-keep';meta();
    const button=disclosure('meta-project-step') as HTMLButtonElement;
    button.click();fixture.detectChanges();
    expect(disclosure('meta-project-step').getAttribute('aria-expanded')).toBe('true');
    expect(disclosure('meta-account-step').getAttribute('aria-expanded')).toBe('false');
    expect(discover).toHaveBeenCalledOnce();
    disclosure('meta-account-step').click();fixture.detectChanges();
    expect(disclosure('meta-account-step').getAttribute('aria-expanded')).toBe('true');
    expect(c.metaOAuth.page_id).toBe('page-to-keep');
    expect(c.metaReviewStep).toBe('account');
    http.expectNone(request => request.method === 'POST');
  });

  it('places campaign deferral in step 2 without revoking the Company account', () => {
    const sync=vi.spyOn(c as any,'syncState').mockImplementation(() => undefined);
    c.metaOAuth.page_id='unsaved-page';const before=structuredClone(c.profile.data);meta();
    const footer=fixture.nativeElement.querySelector('[data-testid="meta-campaign-deferral"]') as HTMLElement;
    expect(footer.closest('app-review-card')).not.toBeNull();
    const button=footer.querySelector('button')!;
    expect(button.textContent).toContain('Set up campaigns later');button.click();
    const request=http.expectOne(request => request.url.includes('/onboarding-deferrals/project/project-1'));
    expect(request.request.body.card).toBe('field:campaigns_defined');
    expect(request.request.body.draft.oauth.page_id).toBe('unsaved-page');
    expect(request.request.body.final_approved).toBeUndefined();
    request.flush({deferrals:{'field:campaigns_defined':{deferred:true,draft:request.request.body.draft}}});
    expect(c.metaAccountState?.account_status).toBe('connected');
    expect(c.profile.data).toEqual(before);expect(sync).toHaveBeenCalledWith('bottom');
  });

  it('offers account deferral inside step 1 when there is no connected account', () => {
    c.metaAccountState={...saved,account_status:'not_connected'} as never;meta();
    expect(fixture.nativeElement.querySelector('[data-testid="meta-campaign-deferral"]')).toBeNull();
    const account=fixture.nativeElement.querySelector('[data-testid="meta-account-step"]') as HTMLElement;
    expect(account.textContent).toContain('Connect Meta later');
    expect(account.querySelector('app-configure-later')).toBeTruthy();
  });

  it('does not render an extra defer control when the active question already offers Configure later', () => {
    const question={...payload,field:'payment_methods',input_type:'multi_select',label:'Payment methods',options:['Bank financing','Configure later'],answer_actions:{'Configure later':{kind:'defer'}}};
    c.messages=[{...message(),ui_payload:question}];c.nextQuestion=question;fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('app-onboarding-ai-message app-configure-later')).toBeNull();
    expect(fixture.nativeElement.querySelector('app-onboarding-response-options')?.textContent).toContain('Configure later');
  });

  it('opens the mobile panel, closes on Escape and restores focus to its trigger', () => {
    const width=window.innerWidth;Object.defineProperty(window,'innerWidth',{value:390,configurable:true});
    try {
      fixture.detectChanges();
      const trigger=fixture.nativeElement.querySelector('button[aria-controls="project-review-panel"]') as HTMLButtonElement;
      trigger.focus();trigger.click();fixture.detectChanges();
      expect(c.reviewPanelOpen).toBe(true);
      expect(document.activeElement?.closest('#project-review-panel')).toBeTruthy();
      const panel=fixture.nativeElement.querySelector('#project-review-panel') as HTMLElement;
      panel.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}));fixture.detectChanges();
      expect(c.reviewPanelOpen).toBe(false);expect(document.activeElement).toBe(trigger);
    } finally {Object.defineProperty(window,'innerWidth',{value:width,configurable:true});}
  });

  it('closes the mobile panel when Property types opens the existing Block B editor', () => {
    vi.useFakeTimers();
    vi.spyOn(c,'loadPropertyTypes').mockImplementation(()=>undefined);
    vi.spyOn(c as any,'loadSalesAssets').mockImplementation(()=>undefined);
    c.reviewPanelOpen=true;c.openEditorTask('catalog');
    expect(c.editorNavigationBusy).toBe(true);expect(c.reviewPanelOpen).toBe(false);
    const request=http.expectOne(request=>request.url.endsWith('/editor/catalog'));
    const next={...payload,input_type:'property_type_catalog',task:'catalog'};
    request.flush({message:{...message(),ui_payload:next},profile:EMPTY_PROJECT_PROFILE,sources:[],next_question:next});
    expect(c.catalogEditorOpen).toBe(true);
    vi.clearAllTimers();vi.useRealTimers();
  });

  it('ignores editor navigation while website extraction is in progress', () => {
    c.onboardingStage='processing';c.openEditorTask('meta_assets');
    expect(c.metaReviewStep).toBe('account');
    http.expectNone(request => request.method==='POST');
  });
  it('does not offer campaign deferral when the Project route is already verified', () => {
    c.metaAccountState={...saved,routing_status:'connected'} as never;meta();
    expect(fixture.nativeElement.querySelector('[data-testid="meta-campaign-deferral"]')).toBeNull();
    expect(c.metaRoutingReviewStatus).toBe('Verified');
    expect(disclosure('meta-account-step').getAttribute('aria-expanded')).toBe('true');
  });

  it('opens step 2 for an explicit campaigns task without associating anything', () => {
    const discover=vi.spyOn(c,'loadMetaAssets').mockImplementation(()=>undefined);
    c.metaOAuth.authorization_id='auth-1';
    (c as any).applyTurn({message:message(),profile:EMPTY_PROJECT_PROFILE,sources:[],next_question:{...payload,task:'meta_assets'}});
    expect(c.metaReviewStep).toBe('assets');expect(discover).toHaveBeenCalledOnce();
    (c as any).applyTurn({message:message(),profile:EMPTY_PROJECT_PROFILE,sources:[],next_question:{...payload,task:'meta_account'}});
    expect(c.metaReviewStep).toBe('account');
    http.expectNone(request=>request.method==='POST');
  });

  it('checks the OAuth return before advancing to campaigns and retains unsaved selection', () => {
    for(const method of ['syncState','loadCampaigns','loadMetaConnections','loadSalesTeam','loadMetaSetupConfiguration','loadMetaSetupState'] as const) {
      vi.spyOn(c as any,method).mockImplementation(()=>undefined);
    }
    vi.spyOn(TestBed.inject(Router),'navigate').mockResolvedValue(true);
    (c as any).route={snapshot:{paramMap:{get:()=> 'project-1'},queryParamMap:{get:(key:string)=>key==='meta_oauth'?'connected':null}}};
    c.metaOAuth.page_id='keep-page';c.showMetaAssetStep=true;c.metaReviewStep='assets';
    initialize.call(c);
    expect(c.metaReviewStep).toBe('account');expect(c.showMetaAssetStep).toBe(false);
    expect(c.metaOAuth.page_id).toBe('keep-page');
    expect(c.metaSetupMessage).toContain('Checking your saved Meta connection');
    vi.mocked(c.loadMetaSetupState).mockRestore();
    c.loadMetaSetupState();
    http.expectOne(request => request.url.includes('/meta/setup-state')).flush(saved);
    expect(c.metaReviewStep).toBe('assets');expect(c.showMetaAssetStep).toBe(true);
    vi.spyOn(c,'loadPropertyTypes').mockImplementation(()=>undefined);
    vi.spyOn(c as any,'loadSalesAssets').mockImplementation(()=>undefined);
    (c as any).applyState({version:1,messages:[message()],profile:EMPTY_PROJECT_PROFILE,sources:[],next_question:{...payload,task:'meta_assets'},stage:'conversation'});
    expect(c.metaReviewStep).toBe('assets');expect(c.showMetaAssetStep).toBe(true);
    http.expectNone(request=>request.method==='POST');
  });

  it('keeps Tab navigation inside the mobile review panel', () => {
    const width=window.innerWidth;Object.defineProperty(window,'innerWidth',{value:390,configurable:true});
    try {
      fixture.detectChanges();c.openProjectReviewPanel();fixture.detectChanges();
      const panel=fixture.nativeElement.querySelector('#project-review-panel') as HTMLElement;
      const controls=Array.from(panel.querySelectorAll<HTMLElement>('button:not([disabled]),a[href],summary,input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex="0"]')).filter(control=>!control.closest('[hidden]'));
      controls.at(-1)!.focus();
      panel.dispatchEvent(new KeyboardEvent('keydown',{key:'Tab',bubbles:true,cancelable:true}));
      expect(document.activeElement).toBe(controls[0]);
      panel.dispatchEvent(new KeyboardEvent('keydown',{key:'Tab',shiftKey:true,bubbles:true,cancelable:true}));
      expect(document.activeElement).toBe(controls.at(-1));
    } finally {Object.defineProperty(window,'innerWidth',{value:width,configurable:true});}
  });

});
