import '@angular/compiler';
import { readFileSync } from 'node:fs';
import { TestBed } from '@angular/core/testing';
import { ChangeDetectorRef, ɵresolveComponentResources as resolveComponentResources } from '@angular/core';
import { BrowserTestingModule, platformBrowserTesting } from '@angular/platform-browser/testing';
import { HttpClient } from '@angular/common/http';
import { of, throwError } from 'rxjs';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { AgentContextComponent } from './agent-context';

TestBed.initTestEnvironment(BrowserTestingModule,platformBrowserTesting());
(AgentContextComponent as any).ctorParameters=()=>[{type:HttpClient},{type:ChangeDetectorRef}];
const template=readFileSync('src/app/shared/ui/agent-context/agent-context.html','utf8');
const saved=()=>({scope_limited:false,chat:{status:'open',cadence:'stopped',cadence_reason:'booked'},
  execution:{workflow_version:'sales-current/1.0',configuration_ready:true,new_engine_selected:true,new_flow_enabled:true,project_ready:true,job_status:'completed'},
  current_interest:{project_name:'Enquiry project',property:'Loft'},
  appointments:[{id:'m',project_name:'Booked project',property_type_name:'Studio',starts_at_utc:'2026-11-10T17:00:00Z',status:'confirmed',specialist_name:'Sales specialist',duration_minutes:45,calendar_status:'failed'}],
  effects:[{id:'op',kind:'booking',status:'review',attempts:5,last_error:'CalendarBindingChanged'}],
  waits:[{id:'w',project_name:'Enquiry project',property:'Loft',date_from:'2026-11-10',date_until:'2026-11-20',timezone:'America/Lima',channel:'sms',status:'review'}],
  trace:{engine:'sales-active/1.0',model:'test/offline',run_status:'completed',last_message_status:'sent',configuration:{version:3}}});
async function mount(inputs:any={},http:any={get:vi.fn(()=>of(saved())),post:vi.fn()}) {
  await resolveComponentResources(url=>Promise.resolve(url.endsWith('.html')?template:''));
  await TestBed.configureTestingModule({imports:[AgentContextComponent],providers:[{provide:HttpClient,useValue:http}]})
    .overrideComponent(AgentContextComponent,{set:{template,templateUrl:undefined,styleUrl:undefined,styles:[],styleUrls:[]}}).compileComponents();
  const fixture=TestBed.createComponent(AgentContextComponent);
  for(const [key,value] of Object.entries(inputs))fixture.componentRef.setInput(key,value);
  fixture.detectChanges();await fixture.whenStable();fixture.detectChanges();
  return {fixture,component:fixture.componentInstance,element:fixture.nativeElement as HTMLElement,http};
}
afterEach(()=>{TestBed.resetTestingModule();vi.restoreAllMocks();});
describe('Operational context template',()=>{
  it('explains an uncertain provider receipt without claiming delivery',async()=>{
    const context={...saved(),trace:{...saved().trace,last_message_status:'delivery_unknown'}};
    const {element}=await mount({context});
    expect(element.textContent).toContain('Provider acceptance is uncertain');
    expect(element.textContent).toContain('automatic resend is stopped');
  });
  it('distinguishes manual responses, pending resume and inactivity from inbound processing',async()=>{
    const context={...saved(),trace:{...saved().trace,last_response_role:'human'},
      continuity:{pending_message_count:2,waiting_for_lead:false,jobs:[{kind:'resume',status:'pending',scheduled_at:'2026-11-10T17:00:00Z'},{kind:'inactivity',status:'review',scheduled_at:'2026-11-10T18:00:00Z'}]},
      handoff_summary:{stage:'S09_HANDOFF',intent_tier:'warm',pending_topics:['materials'],pending_messages:2,last_lead_message:'Send plans'}};
    const {element}=await mount({context});
    expect(element.textContent).toContain('Last responseCompany team');expect(element.textContent).toContain('2 messages');
    expect(element.textContent).toContain('Resume continuation');expect(element.textContent).toContain('Inactivity closing');
    expect(element.textContent).toContain('Sales handoff summary');expect(element.textContent).toContain('Send plans');
  });
  it('keeps the enquiry independent from a recorded visit and labels UTC',async()=>{
    const context=saved(),before=JSON.stringify(context);const {element}=await mount({context});
    const cards=element.querySelectorAll('.property-grid>article');
    expect(cards[0].textContent).toContain('Loft');expect(cards[0].textContent).not.toContain('Studio');
    expect(cards[1].textContent).toContain('Booked project · Studio');expect(cards[1].textContent).toContain('UTC');
    expect(JSON.stringify(context)).toBe(before);
  });
  it('shows the current workflow as separate labeled rows',async()=>{
    const {element}=await mount({context:saved()});
    expect(element.querySelector('.execution')?.textContent).toContain('Current · sales-current/1.0');
    expect(element.querySelectorAll('.execution > div')).toHaveLength(5);
    expect(element.querySelector('.execution')?.textContent).not.toContain('legacy');
  });
  it('shows uncertain availability contact and failed synchronization without implying delivery',async()=>{
    const {element}=await mount({context:saved()});
    expect(element.textContent).toContain('automatic resend is stopped');expect(element.textContent).toContain('CalendarBindingChanged');
    expect(element.textContent).toContain('Provider acceptance does not confirm delivery to the phone');
  });
  it('queues a manager retry only after an explanation and displays the refreshed status',async()=>{
    const refreshed=saved();refreshed.effects[0].status='pending';
    const http={get:vi.fn().mockReturnValueOnce(of(saved())).mockReturnValue(of(refreshed)),post:vi.fn(()=>of({status:'queued_for_recheck'}))};
    const {element,fixture}=await mount({conversationId:'c',canManage:true},http);
    const button=Array.from(element.querySelectorAll('button')).find(b=>b.textContent?.includes('Retry failed synchronization'))!;
    expect(button.disabled).toBe(true);
    const input=element.querySelector('input')!;input.value='Reviewed the saved binding';input.dispatchEvent(new Event('input'));
    fixture.detectChanges();expect(button.disabled).toBe(false);button.click();fixture.detectChanges();await fixture.whenStable();fixture.detectChanges();
    expect(http.post).toHaveBeenCalledWith(expect.stringContaining('/conversations/c/effects/retry'),{kind:'booking',operation_id:'op',note:'Reviewed the saved binding'});
    expect(element.querySelector('[role=status]')?.textContent).toContain('does not mean synchronization has succeeded');
    expect(element.textContent).toContain('booking · pending');
  });
  it('shows retry rejection while keeping the operation in review',async()=>{
    const http={get:vi.fn(()=>of(saved())),post:vi.fn(()=>throwError(()=>new Error('403')))};
    const {component,element,fixture}=await mount({conversationId:'c',canManage:true},http);
    component.note='Reviewed';component.retry(component.data.effects[0]);fixture.detectChanges();
    expect(element.querySelector('[role=alert]')?.textContent).toContain('permissions');
    expect(element.textContent).toContain('booking · review');expect(component.retrying).toBe(false);
  });
  it('keeps Schedule and Monitor read only and hides restricted enquiry details',async()=>{
    const limited={...saved(),scope_limited:true,current_interest:null,tasks:[],trace:{}};
    const {element}=await mount({context:limited,canManage:true});
    expect(element.textContent).toContain('Historical or restricted enquiry context is unavailable');
    expect(element.textContent).not.toContain('Current enquiryLoft');
    expect(Array.from(element.querySelectorAll('button')).some(b=>b.textContent?.includes('Retry'))).toBe(false);
    expect(element.querySelector('input')).toBeNull();
  });
  it('renders evidence as text rather than executable HTML',async()=>{
    const context={...saved(),interventions:[{reason:'THREAT',status:'open',evidence:'<img src=x onerror="alert(1)">'}]};
    const {element}=await mount({context});
    expect(element.textContent).toContain('<img src=x');expect(element.querySelector('img')).toBeNull();
  });
  it('shows a loading failure and recovers through the visible Refresh button',async()=>{
    const http={get:vi.fn().mockReturnValueOnce(throwError(()=>new Error('503'))).mockReturnValue(of(saved())),post:vi.fn()};
    const {element,fixture}=await mount({conversationId:'c'},http);
    expect(element.querySelector('[role=alert]')).not.toBeNull();
    element.querySelector('button')!.click();fixture.detectChanges();await fixture.whenStable();fixture.detectChanges();
    expect(element.querySelector('[role=alert]')).toBeNull();expect(element.textContent).toContain('Loft');
  });
});
