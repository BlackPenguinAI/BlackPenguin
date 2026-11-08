import '@angular/compiler';
import { readFileSync } from 'node:fs';
import { TestBed } from '@angular/core/testing';
import { ChangeDetectorRef, ɵresolveComponentResources as resolveComponentResources } from '@angular/core';
import { BrowserTestingModule, platformBrowserTesting } from '@angular/platform-browser/testing';
import { HttpClient } from '@angular/common/http';
import { ActivatedRoute } from '@angular/router';
import { of } from 'rxjs';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { AgentComponent } from './agent';

TestBed.initTestEnvironment(BrowserTestingModule,platformBrowserTesting());
// Direct Vitest transpilation does not emit Angular constructor metadata.
(AgentComponent as any).ctorParameters=()=>[{type:HttpClient},{type:ChangeDetectorRef},{type:ActivatedRoute}];

describe('Agent review template',()=>{
  afterEach(()=>{TestBed.resetTestingModule();vi.restoreAllMocks();});

  it('renders the incident evidence, requires a note, resumes and displays the review history',async()=>{
    const template=readFileSync('src/app/pages/client/agent/agent.html','utf8');
    await resolveComponentResources(url=>Promise.resolve(url.endsWith('.html') ? template : ''));
    const incident={id:'case',reason:'SECURITY',evidence:'Original message for review',status:'open',created_at:'2026-11-07T17:00:00'};
    const post=vi.fn(()=>of({id:'conversation',lead_name:'Test lead',phone:'+15550100001',channel:'sms',is_paused:false,can_resume:true,
      intervention_cases:[{...incident,status:'false_positive',resolution:{note:'Reviewed with lead',actor_user_id:'reviewer',at:'2026-11-07T17:01:00'}}]}));
    await TestBed.configureTestingModule({imports:[AgentComponent],providers:[
      {provide:HttpClient,useValue:{post}},
      {provide:ActivatedRoute,useValue:{snapshot:{queryParamMap:{get:()=>null}}}},
    ]}).overrideComponent(AgentComponent,{set:{template,
      templateUrl:undefined,styles:[],styleUrls:[]}}).compileComponents();
    vi.spyOn(AgentComponent.prototype,'ngOnInit').mockImplementation(()=>undefined);
    const fixture=TestBed.createComponent(AgentComponent),component=fixture.componentInstance;
    component.role='admin';component.setupOpen=false;component.loading=false;
    component.selected={id:'conversation',lead_name:'Test lead',phone:'+15550100001',channel:'sms',is_paused:true,can_resume:true,
      pause_reason:'Human intervention: security review',intervention_cases:[incident]};
    vi.spyOn(component,'loadConversations').mockImplementation(()=>undefined);
    fixture.detectChanges();await fixture.whenStable();
    const element:HTMLElement=fixture.nativeElement;
    expect(element.querySelector('[aria-label="Conversation pause review"]')?.textContent).toContain(incident.evidence);
    const button=Array.from(element.querySelectorAll('button')).find(b=>b.textContent?.includes('False positive · resume AI'))!;
    expect(button.disabled).toBe(true);
    const textarea=element.querySelector('textarea[placeholder="Explain the review or why this was a false positive"]') as HTMLTextAreaElement;
    textarea.value='Reviewed with lead';textarea.dispatchEvent(new Event('input'));
    fixture.detectChanges();await fixture.whenStable();fixture.detectChanges();
    expect(button.disabled).toBe(false);button.click();
    fixture.detectChanges();await fixture.whenStable();fixture.detectChanges();
    expect(post).toHaveBeenCalledWith(expect.stringContaining('/action'),expect.objectContaining({false_positive:true,review_case_id:'case',review_note:'Reviewed with lead'}));
    expect(element.querySelector('[aria-label="Conversation pause review"]')).toBeNull();
    expect(element.textContent).toContain('false_positive');
    expect(element.textContent).toContain('Reviewed with lead');
  });
});
