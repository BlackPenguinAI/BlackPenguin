import '@angular/compiler';
import { afterEach,describe,it,expect,vi } from 'vitest';
import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController,provideHttpClientTesting } from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';
import { MarketingComponent } from './marketing';
import { OnboardingResponseOptionsComponent as Options } from '../../../shared/ui/onboarding-response-options/onboarding-response-options';
import { ProjectChatComponent } from '../projects/project-chat/project-chat';

afterEach(()=>{vi.restoreAllMocks();TestBed.resetTestingModule();});
function summary(overrides:any={}) {return {project_id:'p',project_name:'Project P',can_configure_meta:false,leads:[],campaigns:[],totals:{leads:0,qualified:0,appointments:0,active_campaigns:0,follow_up_rate:0,conversion_rate:0},
  meta_setup:{account_status:'connected',routing_status:'not_linked',authorizations:[],last_authorization:{meta_user_name:'Saved account',status:'active',expires_at:'2026-12-01T12:00:00'},missing_permissions:[],mappings:[]},...overrides};}
function render(data:any) {
  vi.spyOn(MarketingComponent.prototype,'ngOnInit').mockImplementation(()=>{});
  TestBed.configureTestingModule({imports:[MarketingComponent],providers:[provideHttpClient(),provideRouter([])]});
  const f=TestBed.createComponent(MarketingComponent);f.componentInstance.loading=false;f.componentInstance.projectId='p';f.componentInstance.summary=data;f.detectChanges();return f;
}
describe('Marketing Meta state',()=>{
 it('shows connected account with no associations, rather than implying disconnection',()=>{
  const f=render(summary());const html=f.nativeElement as HTMLElement;
  expect(html.querySelector('[data-testid=marketing-meta-account]')?.textContent).toContain('Account authorized');
  expect(html.querySelector('[data-testid=marketing-meta-routing]')?.textContent).toContain('No Meta campaigns or forms linked');
  expect(html.textContent).toContain('Authorization expires:');expect(html.textContent).toContain('(UTC)');
 });
 it('shows read-only guidance for Marketing without unusable onboarding links',()=>{
  const f=render(summary());expect(f.nativeElement.textContent).toContain('Read-only setup status');expect(f.nativeElement.querySelector('.meta-state a')).toBeNull();
 });
 it('links managers to the correct account and mapping tasks',()=>{
  const f=render(summary({can_configure_meta:true}));const links=[...f.nativeElement.querySelectorAll('.meta-state a')].map((a:any)=>a.getAttribute('href'));
  expect(links).toEqual(['/app/projects/p/onboarding?task=meta_account','/app/projects/p/onboarding?task=meta_assets']);
 });
 it('does not turn unknown setup state into a disconnected assertion',()=>{
  const f=render(summary({meta_setup:null}));expect(f.nativeElement.textContent).toContain('Meta status is unavailable');expect(f.nativeElement.textContent).not.toContain('No Meta account connected');
 });
 it.each(['permissions_required','reconnect_required'])('shows %s independently from routing',(account_status)=>{
  const f=render(summary({meta_setup:{account_status,routing_status:'not_linked',last_authorization:{expires_at:'2026-10-01T12:00:00',status:'active'},missing_permissions:['leads_retrieval'],mappings:[]}}));
  expect(f.nativeElement.textContent).toContain(account_status==='permissions_required' ? 'permissions missing' : 'reconnect required');expect(f.nativeElement.textContent).toContain('leads_retrieval');
 });
 it('lists saved inactive forms with their actual reason',()=>{
  const f=render(summary({meta_setup:{account_status:'connected',routing_status:'review_required',mappings:[{name:'Draft campaign',campaign_status:'draft',reason:'inactive_campaign',page_id:'page',lead_form_id:'form'}]}}));
  expect(f.nativeElement.textContent).toContain('Campaign is not active');expect(f.nativeElement.textContent).toContain('Form: form');expect(f.nativeElement.textContent).not.toContain('Active Project route verified');
 });
 it('cancels old Project requests and clears stale summary and campaign filter',()=>{
  TestBed.configureTestingModule({imports:[MarketingComponent],providers:[provideHttpClient(),provideHttpClientTesting(),provideRouter([])]});const f=TestBed.createComponent(MarketingComponent);const c=f.componentInstance;const http=TestBed.inject(HttpTestingController);
  c.projectId='a';c.summary=summary();c.selectedCampaignId='old';c.reload();const first=http.expectOne(r=>r.url.endsWith('/a/marketing/summary'));
  c.projectId='b';c.reload();expect(first.cancelled).toBe(true);expect(c.summary).toBeNull();expect(c.selectedCampaignId).toBe('');
  http.expectOne(r=>r.url.endsWith('/b/marketing/summary')).flush(summary({project_id:'b',project_name:'B'}));expect(c.summary.project_name).toBe('B');
  c.reload();http.expectOne(r=>r.url.endsWith('/b/marketing/summary')).flush({}, {status:500,statusText:'Error'});expect(c.summary).toBeNull();expect(c.error).toContain('Retry');http.verify();
 });
 it('clears setup and leads when no Project is selected',()=>{
  const f=render(summary());const c=f.componentInstance;c.leads=[{id:'old'}];c.projectId='';c.reload();expect(c.summary).toBeNull();expect(c.leads).toEqual([]);expect(c.loading).toBe(false);
 });
 it('normalizes naive server dates as UTC without changing offsets',()=>{
  const f=render(summary());expect(f.componentInstance.asUtc('2026-12-01T12:00:00')).toBe('2026-12-01T12:00:00Z');expect(f.componentInstance.asUtc('2026-12-01T12:00:00-05:00')).toBe('2026-12-01T12:00:00-05:00');
 });
 it('opens the requested editor only after explicit confirmation',()=>{
  vi.spyOn(ProjectChatComponent.prototype,'ngOnInit').mockImplementation(()=>{});
  TestBed.configureTestingModule({imports:[ProjectChatComponent],providers:[provideHttpClient(),provideRouter([])]});const f=TestBed.createComponent(ProjectChatComponent);const c=f.componentInstance;
  c.initialState='ready';c.requestedEditorTask='meta_assets';const open=vi.spyOn(c,'openEditorTask').mockImplementation(()=>{});f.detectChanges();expect(open).not.toHaveBeenCalled();
  (f.nativeElement.querySelector('[data-testid=requested-editor-task] button') as HTMLButtonElement).click();expect(open).toHaveBeenCalledWith('meta_assets');
 });
});

function options(extra:any={}) {const c=new Options();c.question={field:'compliance_notes',label:'Compliance',prompt:'Choose',input_type:'multi_select',options:['Standard','A','B','Not applicable','Provide later'],examples:[],allow_custom:true,minimum_words:null,exclusive_options:['Standard'],answer_actions:{'Not applicable':{kind:'not_applicable'},'Provide later':{kind:'defer'}},...extra};return c;}
describe('Existing multi-select safety',()=>{
 it('treats default compliance as exclusive in both click orders',()=>{
  const c=options();c.choose('A');c.choose('B');c.choose('Standard');expect([...c.selectedValues]).toEqual(['Standard']);c.choose('A');expect([...c.selectedValues]).toEqual(['A']);
 });
 it.each(['Not applicable'])('emits %s alone as a typed action',(choice)=>{
  const c=options();const emitted:Array<string|string[]>=[];c.selected.subscribe(v=>emitted.push(v));c.choose('A');c.choose(choice);expect(emitted).toEqual([choice]);expect(c.selectedValues.size).toBe(0);
 });
 it('preserves selected values when postponing instead of submitting an answer',()=>{const c=options();const draft=vi.fn();const selected=vi.fn();c.deferred.subscribe(draft);c.selected.subscribe(selected);c.choose('A');c.choose('Provide later');expect(draft).toHaveBeenCalledWith(['A']);expect(selected).not.toHaveBeenCalled();expect(c.selectedValues.has('A')).toBe(true);});
 it('restores saved and custom values for editing, requiring explicit submit',()=>{
  const c=options({selected_values:['A','Custom saved value']});const emitted:Array<string|string[]>=[];c.selected.subscribe(v=>emitted.push(v));c.ngOnChanges();expect(c.choices).toContain('Custom saved value');expect(emitted).toEqual([]);c.submitSelection();expect(emitted).toEqual([['A','Custom saved value']]);
 });
 it('does not leak selections to another field',()=>{
  const c=options();c.choose('A');c.question={...c.question,field:'payment_methods',selected_values:['B']};c.ngOnChanges();expect([...c.selectedValues]).toEqual(['B']);
 });
 it('keeps pending choices when the same question payload is refreshed',()=>{
  const c=options({selected_values:['A']});c.ngOnChanges();c.choose('B');c.question={...c.question};c.ngOnChanges();expect([...c.selectedValues]).toEqual(['A','B']);
 });
 it('blocks an incompatible historical combination until reviewed',()=>{
  const c=options({selected_values:['Standard','A']});const emit=vi.spyOn(c.selected,'emit');c.ngOnChanges();expect(c.selectionConflict).toBe(true);c.submitSelection();expect(emit).not.toHaveBeenCalled();c.choose('Standard');expect(c.selectionConflict).toBe(false);
 });
 it.each(['disabled','answered'])('does not submit or change %s cards',(key)=>{
  const c=options();(c as any)[key]=true;const emit=vi.spyOn(c.selected,'emit');c.choose('A');c.submitSelection();expect(emit).not.toHaveBeenCalled();
 });
 it('keeps single-select fields single',()=>{
  const c=options({field:'project_type',input_type:'single_select',options:['Mixed-use']});const emit=vi.spyOn(c.selected,'emit');c.choose('Mixed-use');expect(emit).toHaveBeenCalledWith('Mixed-use');expect(c.isMultiSelect).toBe(false);
 });
 it('keeps example-only multi fields multiple and restores custom values',()=>{
  const c=options({field:'public_contact_emails',options:[],examples:['info@example.test','sales@example.test'],selected_values:['saved@example.test']});const emit=vi.spyOn(c.selected,'emit');c.ngOnChanges();expect(c.choices).toContain('saved@example.test');c.choose('info@example.test');c.choose('sales@example.test');expect(emit).not.toHaveBeenCalled();c.submitSelection();expect(emit).toHaveBeenCalledWith(['saved@example.test','info@example.test','sales@example.test']);
 });
});
