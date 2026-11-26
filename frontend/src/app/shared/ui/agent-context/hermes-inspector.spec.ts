import '@angular/compiler';
import { TestBed } from '@angular/core/testing';
import { BrowserTestingModule, platformBrowserTesting } from '@angular/platform-browser/testing';
import { of, Subject } from 'rxjs';
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { HermesInspectorComponent, HermesInspectorView } from './hermes-inspector';
import { AgentContextComponent } from './agent-context';

function saved(lead='lead'): HermesInspectorView {
  return {
    version:'hermes-conversation-inspector/1.0',scope:{conversation_id:'c',company_id:'co',project_id:'p',lead_id:lead},
    routing:{active_sales_engine:'langgraph',effective_sales_engine:'langgraph',target_default_engine:'hermes',hermes_live_ready:false,error_code:null},
    has_state:true,historical_state:false,revision:8,updated_at:'2026-11-26T18:02:15Z',engine_version:'test',
    last_engine:'hermes',last_run_engine:'hermes',conversation_engine:'hermes',channel:'sms',project_name:'Project',timezone:'America/Lima',
    phase:'property_exploration',phase_source:'observed',focus:{id:'van',name:'Van Buren',kind:'property_type',price:325000,price_kind:'starting',currency:'USD',bedrooms:3},focus_status:'resolved',presented_properties:[],
    primary_preferences:{revision:3,source:{message_id:'inbound',at:'2026-11-26T18:02:15Z'},budget:{mode:'cap',currency:'USD',minimum_usd:null,maximum_usd:350000,target_usd:null,exact_price_usd:null},bedrooms:{mode:'exact',minimum:null,maximum:null,preferred:3}},
    crm_facts:{},active_search:{scope:'temporary',criteria:{bedrooms:4},matches:[],source:null,match_count:2},property_filters:{},
    visit_draft:null,confirmation:null,visit_planning_paused:false,slot_offer:null,
    visits:[{id:'visit',property_name:'Oakwood',status:'confirmed',confirmation_status:'confirmed',calendar_status:'pending',starts_at:'2026-12-02T15:00:00Z',timezone:'America/Lima',duration_minutes:60,address:null,specialist:null,active:true}],
    materials:[{asset_id:'a',name:'Brochure',tags:['brochure'],status:'provider_accepted',access_status:'active'}],operations:[],
    timeline:[{kind:'message',at:'2026-11-26T18:02:15Z',message_id:'inbound',engine:'lead',status:'received',direction:'inbound'}],
  };
}

beforeAll(()=>TestBed.initTestEnvironment(BrowserTestingModule,platformBrowserTesting()));
afterEach(()=>{TestBed.resetTestingModule();vi.useRealTimers();});

describe('HEI-04 inspector',()=>{
  it('renders preferences and distinguishes temporary search and evidence',async()=>{
    await TestBed.configureTestingModule({imports:[HermesInspectorComponent]}).compileComponents();
    const fixture=TestBed.createComponent(HermesInspectorComponent);
    fixture.componentRef.setInput('conversationId','c');fixture.componentRef.setInput('inspector',saved());fixture.detectChanges();
    const element=fixture.nativeElement as HTMLElement;
    expect(element.textContent).toContain('350,000');expect(element.textContent).toContain('Exactly 3');
    expect(element.textContent).toContain('Primary preferences preserved');
    expect(element.textContent).toContain('13:02:15');
    fixture.componentInstance.showEvidence('inbound');fixture.detectChanges();
    expect(element.querySelector('a[href="#agent-message-inbound"]')).not.toBeNull();
    expect(element.querySelector('.highlight')).not.toBeNull();
  });
  it('renders property, recorded visits and provider status separately',async()=>{
    await TestBed.configureTestingModule({imports:[HermesInspectorComponent]}).compileComponents();
    const fixture=TestBed.createComponent(HermesInspectorComponent);
    fixture.componentRef.setInput('conversationId','c');fixture.componentRef.setInput('inspector',saved());fixture.detectChanges();
    fixture.componentInstance.tab='property';fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('Van Buren');
    expect(fixture.nativeElement.textContent).toContain('Provider accepted · delivery not confirmed');
    expect(fixture.nativeElement.textContent).not.toContain('Oakwood');
    fixture.componentInstance.tab='visits';fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('Oakwood');expect(fixture.nativeElement.textContent).toContain('Calendar: pending');
  });
  it('resets evidence when the same conversation is assigned to another lead',()=>{
    const c=new HermesInspectorComponent();c.conversationId='c';c.inspector=saved();c.ngOnChanges();
    c.showEvidence('inbound');c.inspector=saved('new-lead');c.ngOnChanges();
    expect(c.tab).toBe('profile');expect(c.selectedEvidence).toBeNull();c.conversationId='other';expect(c.view).toBeNull();
  });
  it('reuses operational polling and rejects a response from the previous opportunity',()=>{
    vi.useFakeTimers();const previous=new Subject<any>();
    const get=vi.fn().mockReturnValueOnce(previous).mockReturnValueOnce(of({inspector_scope:{conversation_id:'c',lead_id:'old',project_id:'p'},hermes_inspector:saved('old')})).mockReturnValue(of({inspector_scope:{conversation_id:'c',lead_id:'new',project_id:'p'},hermes_inspector:saved('new')}));
    const c=new AgentContextComponent({get} as any);c.conversationId='c';c.leadId='old';c.projectId='p';c.ngOnChanges();
    c.leadId='new';c.ngOnChanges();previous.next({inspector_scope:{conversation_id:'c',lead_id:'old',project_id:'p'}});
    expect(c.data).toBeNull();expect(c.error).toContain('selection changed');
    vi.advanceTimersByTime(10000);expect(c.data.hermes_inspector.scope.lead_id).toBe('new');
    expect(get.mock.calls.every(([url])=>String(url).endsWith('/operational-context'))).toBe(true);c.ngOnDestroy();
  });
});
