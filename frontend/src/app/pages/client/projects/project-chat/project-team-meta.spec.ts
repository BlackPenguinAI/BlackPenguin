import '@angular/compiler';
import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { of, Subject, throwError } from 'rxjs';
import { ProjectChatComponent } from './project-chat';
import { ProjectOnboardingService } from './project-onboarding.service';
import { EMPTY_PROJECT_PROFILE } from './project-onboarding.models';
import { MetaOAuthWindow } from '../../../../shared/utils/meta-oauth-window';
import { API_V1_URL } from '../../../../core/config/api.config';

const callbackOrigin=new URL(API_V1_URL,window.location.href).origin;
const start={authorization_url:'https://www.facebook.com/v26.0/dialog/oauth?state=nonce-1',state:'nonce-1',expires_at:new Date(Date.now()+600000).toISOString()};
const emptyAssets={authorizations:[],pages:[],ad_accounts:[],lead_forms:[],campaigns:[],adsets:[],ads:[],warnings:[]};
const savedAuth={id:'auth-1',meta_user_id:'meta-person',meta_user_name:'Saved person',scopes:[],status:'active',expires_at:null,created_at:''};
const savedState={project_id:'project-1',account_status:'connected' as const,authorizations:[savedAuth],last_authorization:savedAuth,missing_permissions:[],routing_status:'not_linked' as const,mappings:[]};
function service() {
  return {applyOnboardingAction:vi.fn(),getMetaSetupState:vi.fn(()=>of(savedState)),getMetaAuthorizations:vi.fn(()=>of([savedAuth])),
    getCampaigns:vi.fn(()=>of([])),getMetaConnections:vi.fn(()=>of([])),discoverMetaAssets:vi.fn(()=>of(emptyAssets)),
    getProjectTeam:vi.fn(()=>of([])),getSalesCandidates:vi.fn(()=>of([])),startMetaOAuth:vi.fn(()=>of(start))};
}
function component(api:any=service()) {
  const c=new ProjectChatComponent({} as never,api,{detectChanges:vi.fn()} as never,{isSupported:false,abort:vi.fn()} as never,{} as never);
  c.projectId='project-1';vi.spyOn(c as any,'syncState').mockImplementation(()=>undefined);
  return c;
}
function popup() {
  const child={closed:false,close:vi.fn(),location:{replace:vi.fn()}} as any;
  vi.spyOn(window,'open').mockReturnValue(child);
  return child;
}
function result(child:any,data:any={},origin=callbackOrigin) {
  window.dispatchEvent(new MessageEvent('message',{origin,source:child,data:{type:'bp-meta-oauth',state:'nonce-1',status:'connected',project_id:'project-1',...data}}));
}
afterEach(()=>{vi.useRealTimers();vi.restoreAllMocks();TestBed.resetTestingModule();});

describe('Auxiliary Meta OAuth window',()=>{
  it('accepts only exact origin, source window, state, project and result type',()=>{
    const child=popup(),done=vi.fn(),bridge=new MetaOAuthWindow(callbackOrigin,'project-1',done);
    expect(bridge.open()).toBe(true);bridge.authorize(start);
    result(child,{},'https://attacker.test');result(window);result(child,{state:'wrong'});
    result(child,{project_id:'other'});result(child,{status:'unexpected'});result(child,{type:'other'});
    expect(done).not.toHaveBeenCalled();
    result(child);result(child);
    expect(done).toHaveBeenCalledOnce();expect(done).toHaveBeenCalledWith({status:'connected',reason:''});
    expect(child.location.replace).toHaveBeenCalledWith(start.authorization_url);
  });
  it('handles a blocked popup without navigating the opener',()=>{
    vi.spyOn(window,'open').mockReturnValue(null);
    const bridge=new MetaOAuthWindow(callbackOrigin,'project-1',vi.fn());
    const before=window.location.href;
    expect(bridge.open()).toBe(false);bridge.authorize(start);
    expect(window.location.href).toBe(before);bridge.dispose();
  });
  it.each([
    ['https://attacker.test/dialog/oauth?state=nonce-1','nonce-1'],
    ['https://www.facebook.com/dialog/oauth?state=wrong','nonce-1'],
    ['javascript:alert(1)','nonce-1'],
  ])('rejects unsafe authorization URL %s',(authorization_url,state)=>{
    const child=popup(),bridge=new MetaOAuthWindow(callbackOrigin,'project-1',vi.fn());bridge.open();
    expect(()=>bridge.authorize({...start,authorization_url,state})).toThrow();
    expect(child.location.replace).not.toHaveBeenCalled();bridge.dispose();
  });
  it('reports cancellation and removes listeners after the window closes',()=>{
    vi.useFakeTimers();const child=popup(),done=vi.fn(),bridge=new MetaOAuthWindow(callbackOrigin,'project-1',done);
    bridge.open();bridge.authorize(start);child.closed=true;vi.advanceTimersByTime(501);result(child);
    expect(done).toHaveBeenCalledOnce();expect(done.mock.calls[0][0].reason).toContain('closed');
  });
  it('expires an authorization attempt and can dispose without callbacks',()=>{
    vi.useFakeTimers();popup();const done=vi.fn(),bridge=new MetaOAuthWindow(callbackOrigin,'project-1',done);
    bridge.open();bridge.authorize({...start,expires_at:new Date(Date.now()+1000).toISOString()});
    vi.advanceTimersByTime(1500);expect(done.mock.calls[0][0].reason).toContain('expired');
    const another=new MetaOAuthWindow(callbackOrigin,'project-1',done);another.open();another.dispose();
    vi.advanceTimersByTime(700000);expect(done).toHaveBeenCalledOnce();
  });
});

describe('Project team and independent Meta steps',()=>{
  it('uses same-tab OAuth, persists drafts, and ignores duplicate connection clicks',()=>{
    const api=service(),pending=new Subject<typeof start>();api.startMetaOAuth.mockReturnValue(pending as any);
    const c=component(api);const navigate=vi.spyOn(c,'navigateToMeta').mockImplementation(()=>undefined);
    c.prompt='Unsaved chat';c.propertyTypeDraft.name='Unsaved unit';c.metaOAuth.page_id='draft-page';c.metaOAuth.campaign_name='Draft campaign';
    c.connectMeta();c.connectMeta();expect(api.startMetaOAuth).toHaveBeenCalledOnce();
    expect(navigate).not.toHaveBeenCalled();pending.next(start);
    expect(navigate).toHaveBeenCalledWith(start.authorization_url);
    expect(JSON.parse(sessionStorage.getItem('bp-meta-draft:project-1')!).prompt).toBe('Unsaved chat');
    const restored=component(api);(restored as any).restoreOAuthDraft();
    expect(restored.metaOAuth.page_id).toBe('draft-page');expect(restored.metaOAuth.campaign_name).toBe('Draft campaign');
    sessionStorage.removeItem('bp-meta-draft:project-1');
  });
  it('rejects unsafe destinations and recovers from start errors',()=>{
    const api=service(),c=component(api),navigate=vi.spyOn(c,'navigateToMeta').mockImplementation(()=>undefined);
    api.startMetaOAuth.mockReturnValue(of({...start,authorization_url:'https://attacker.test'}) as any);
    c.connectMeta();expect(navigate).not.toHaveBeenCalled();expect(c.metaOAuthBusy).toBe(false);
    api.startMetaOAuth.mockReturnValue(throwError(()=>new Error('offline')) as any);
    c.connectMeta();expect(c.metaLoginBusy).toBe(false);expect(c.errorMessage).toContain('unchanged');
  });
  it('bounds an unresponsive OAuth start without losing the draft',()=>{
    vi.useFakeTimers();const api=service();api.startMetaOAuth.mockReturnValue(new Subject() as any);
    const c=component(api);c.propertyTypeDraft.name='Keep';c.connectMeta();vi.advanceTimersByTime(20001);
    expect(c.metaOAuthBusy).toBe(false);expect(c.metaLoginBusy).toBe(false);expect(c.propertyTypeDraft.name).toBe('Keep');
  });
  it('opens verified account assets for review without associating them',()=>{
    const api=service(),c=component(api);c.loadMetaAuthorizations();c.loadMetaSetupState();
    expect(c.metaOAuth.authorization_id).toBe('auth-1');expect(c.metaAccountState?.routing_status).toBe('not_linked');
    expect(c.metaReviewStep).toBe('assets');expect(api.discoverMetaAssets).toHaveBeenCalledOnce();
    expect(api.applyOnboardingAction).not.toHaveBeenCalled();
  });
  it('ignores a stale asset discovery response after a different account is selected',()=>{
    const api=service();const first=new Subject<any>(),second=new Subject<any>();let calls=0;
    api.discoverMetaAssets.mockImplementation(()=>++calls===1 ? first as any : second as any);
    const c=component(api);c.metaOAuth.authorization_id='first';c.loadMetaAssets();
    c.metaOAuth.authorization_id='second';c.metaAuthorizationChanged();
    second.next({...emptyAssets,warnings:['Second account']});first.next({...emptyAssets,warnings:['Stale account']});
    expect(c.metaAssets.warnings).toEqual(['Second account']);
  });
  it('does not restore an old persisted Meta selection over current local edits on refresh',()=>{
    const c=component();vi.spyOn(c,'loadPropertyTypes').mockImplementation(()=>undefined);vi.spyOn(c,'loadSalesAssets').mockImplementation(()=>undefined);
    const state={version:1,messages:[],profile:{...EMPTY_PROJECT_PROFILE,ui_deferrals:{'field:campaigns_defined':{deferred:true,draft:{oauth:{campaign_name:'Saved'}},updated_at:'2026-11-04'}}},stage:'conversation',sources:[],next_question:null};
    (c as any).applyState(state);expect(c.metaOAuth.campaign_name).toBe('Saved');
    c.metaOAuth.campaign_name='Current unsaved';(c as any).applyState({...state,version:2});
    expect(c.metaOAuth.campaign_name).toBe('Current unsaved');
  });
  it('keeps an Administrator with Sales and Marketing capabilities recognized as Sales',()=>{
    const c=component();c.projectTeam=[{id:'a',user_id:'admin',responsibility:'marketing',sales_enabled:true,marketing_enabled:true,is_active:true,accepts_new_leads:true} as any];
    expect(c.assignedSalesUsers).toHaveLength(1);
  });
});

async function render(inputType:string) {
  vi.spyOn(ProjectChatComponent.prototype,'ngOnInit').mockImplementation(()=>undefined);
  TestBed.configureTestingModule({imports:[ProjectChatComponent],providers:[provideHttpClient(),provideRouter([])]});
  const fixture=TestBed.createComponent(ProjectChatComponent),c=fixture.componentInstance;
  c.projectId='project-1';c.initialState='ready';c.messages=[{id:'q',sender:'ai',content:'Setup',created_at:new Date(),attachments:[],ui_payload:{input_type:inputType,field:inputType==='project_sales_team'?'sales_contacts':'campaigns_defined',label:'Setup',prompt:'Setup'}} as any];
  vi.spyOn(c,'isActiveQuestion').mockReturnValue(true);
  vi.spyOn(c,'canManageProjectTeam','get').mockReturnValue(true);
  c.metaAccountState={...savedState};c.metaAuthorizations=[savedAuth];
  c.metaSetupConfig={...c.metaSetupConfig,oauth_enabled:true};
  fixture.detectChanges();await fixture.whenStable();return fixture;
}

it('renders only existing-user assignment with a safe Team link and refresh, never user creation',async()=>{
  const f=await render('project_sales_team'),html=f.nativeElement as HTMLElement;
  expect(html.textContent).toContain('Only existing Company users');expect(html.textContent).toContain('all current and future Projects');
  expect(html.textContent).not.toContain('Create and assign Sales user');
  expect(html.querySelector('input[type=email]')).toBeNull();
  const link=html.querySelector('a[href="/app/users"]');expect(link?.getAttribute('target')).toBe('_blank');expect(link?.getAttribute('rel')).toContain('noopener');
  const refresh=vi.spyOn(f.componentInstance,'loadSalesTeam').mockImplementation(()=>undefined);
  [...html.querySelectorAll('button')].find(b=>b.textContent?.includes('Refresh existing users'))!.click();expect(refresh).toHaveBeenCalledOnce();
  f.destroy();
});

it('renders saved Meta states with a single campaign deferral after account connection',async()=>{
  const f=await render('meta_lead_setup'),html=f.nativeElement as HTMLElement;
  expect(html.querySelector('[data-testid=meta-account-step]')).not.toBeNull();
  expect(html.querySelector('[data-testid=meta-project-step]')).not.toBeNull();
  expect(html.querySelector('[data-testid=meta-account-status]')?.textContent).toContain('authorized');
  expect(html.querySelector('[data-testid=meta-routing-status]')?.textContent).toContain('No campaign');
  expect(html.querySelectorAll('app-configure-later')).toHaveLength(1);
  expect(html.querySelector('[data-testid=meta-account-step]')?.querySelectorAll('app-configure-later')).toHaveLength(0);
  expect(html.querySelector('[data-testid=meta-campaign-deferral]')?.querySelectorAll('app-configure-later')).toHaveLength(1);
  expect(html.textContent).toContain('Set up campaigns later');
  expect(html.querySelector('iframe')).toBeNull();expect(html.querySelector('[data-testid=meta-saved-summary]')).toBeNull();
  f.destroy();
});

it('uses scoped API requests and assigns Sales without resetting Marketing',()=>{
  TestBed.configureTestingModule({providers:[provideHttpClient(),provideHttpClientTesting()]});
  const api=TestBed.inject(ProjectOnboardingService),http=TestBed.inject(HttpTestingController);
  api.assignSalesUser('project-1','admin').subscribe();
  const assign=http.expectOne(r=>r.url.endsWith('/projects/project-1/team/admin'));
  expect(assign.request.body.sales_enabled).toBe(true);expect(assign.request.body).not.toHaveProperty('marketing_enabled');assign.flush({});
  api.getMetaSetupState('project-1').subscribe();const state=http.expectOne(r=>r.url.endsWith('/projects/project-1/meta/setup-state'));
  expect(state.request.method).toBe('GET');state.flush(savedState);http.verify();
});

it('does not report a Project route ready because another Company connection was verified',()=>{
  const c=component();c.metaConnections=[{id:'another-project-connection',verification_status:'succeeded'} as any];
  c.metaAccountState={...savedState};expect(c.metaActivationLabel).toBe('Account saved · Project route pending');
  c.metaAccountState={...savedState,routing_status:'connected'};expect(c.metaActivationLabel).toBe('Project route verified');
});

it('shows role guidance and disables assignment controls for Marketing',async()=>{
  const f=await render('project_sales_team'),c=f.componentInstance;
  vi.spyOn(c,'canManageProjectTeam','get').mockReturnValue(false);f.detectChanges();await f.whenStable();
  const html=f.nativeElement as HTMLElement;
  expect(html.querySelector('a[href="/app/users"]')).toBeNull();
  expect(html.textContent).toContain('Ask the Company Administrator or Assistant');
  expect([...html.querySelectorAll('select')].some(select=>select.disabled)).toBe(true);f.destroy();
});

