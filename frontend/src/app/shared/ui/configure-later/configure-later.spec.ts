import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { ConfigureLaterComponent, restoreDraft } from './configure-later';
import { ChatComponent } from '../../../pages/chat/chat';
import { ProjectChatComponent } from '../../../pages/client/projects/project-chat/project-chat';

describe('Uniform Configure later',()=>{
  let http:HttpTestingController; let component:ConfigureLaterComponent;
  beforeEach(()=>{ TestBed.configureTestingModule({imports:[ConfigureLaterComponent],providers:[provideHttpClient(),provideHttpClientTesting()]});http=TestBed.inject(HttpTestingController);component=TestBed.createComponent(ConfigureLaterComponent).componentInstance;component.entityId='project-1';component.card='field:campaigns_defined'; });
  afterEach(()=>{http.verify();TestBed.resetTestingModule();});
  it('keeps the existing shared labels unless contextual text is requested',()=>{
    expect(component.buttonLabel).toBe('Complete later');
    component.label='Project campaigns and forms';component.contextual=true;
    expect(component.buttonLabel).toBe('Review Project campaigns and forms later');
    component.actionLabel='Set up campaigns later';expect(component.buttonLabel).toBe('Set up campaigns later');
    component.records={[component.card]:{deferred:true,draft:{}}};
    expect(component.buttonLabel).toBe('Resume Project campaigns and forms');
  });
  it('does not write deferrals while its parent operation is blocked',()=>{
    component.blocked=true;component.save();http.expectNone(()=>true);
    expect(component.busy).toBe(false);
  });
  it('persists the draft without authorizing sales, approving files or applying facts',()=>{
    component.draft={manual:{page_id:'12345'},oauth:{campaign_name:'Draft launch'}};
    component.save();
    const request=http.expectOne('http://localhost:8000/api/v1/onboarding-deferrals/project/project-1');
    expect(request.request.body).toEqual({card:'field:campaigns_defined',resume:false,draft:component.draft});
    expect(request.request.body.final_approved).toBeUndefined();
    request.flush({deferrals:{'field:campaigns_defined':{deferred:true,draft:component.draft}}});
    expect(component.records[component.card].deferred).toBe(true);expect(component.busy).toBe(false);
  });
  it('resumes the saved card rather than confirming it',()=>{
    component.records={'field:campaigns_defined':{deferred:true,draft:{answer:'Saved input'}}};component.save();
    const request=http.expectOne(r=>r.url.includes('/onboarding-deferrals/'));
    expect(request.request.body.resume).toBe(true);request.flush({deferrals:{'field:campaigns_defined':{deferred:false,draft:{answer:'Saved input'}}}});
    expect(component.records[component.card].draft['answer']).toBe('Saved input');
  });
  it('keeps drafts and gives a readable failure without claiming approval',()=>{
    component.draft={answer:'Do not lose this'};component.save();
    http.expectOne(r=>r.url.includes('/onboarding-deferrals/')).flush({detail:'Draft is too large'},{status:413,statusText:'Too large'});
    expect(component.draft['answer']).toBe('Do not lose this');expect(component.error).toBe('Draft is too large');expect(component.busy).toBe(false);
  });
  it('restores editable values without overwriting identity or approval status',()=>{
    const target={id:'a',project_id:'p',review_status:'candidate',name:'Original',starting_price:30};
    restoreDraft(target,{id:'b',project_id:'other',review_status:'confirmed',name:'Unsaved name',starting_price:50,unknown:'ignored'});
    expect(target).toEqual({id:'a',project_id:'p',review_status:'candidate',name:'Unsaved name',starting_price:50});
  });
  it('does not restore an older catalog draft over a newly saved property',()=>{
    const page:any=Object.create(ProjectChatComponent.prototype);
    page.propertyTypeImageSelection=new Map();
    page.propertyTypeBases=new Map();page.consumedPropertyDrafts=new Map();page.dirtyPropertyTypeIds=new Set();
    page.profile={ui_deferrals:{'field:property_type_catalog':{updated_at:'2026-11-04T10:00:00',draft:{items:[{id:'a',name:'Old draft'}]}}}};
    const result=page.normalizePropertyType({id:'a',name:'Latest saved name',updated_at:'2026-11-04T11:00:00',inventory_updated_at:null});
    expect(result.name).toBe('Latest saved name');
  });
  for(const [name,Type] of [['Company',ChatComponent],['Project',ProjectChatComponent]] as const) {
    it(name+' distinguishes deferred source review from approved review after reload',()=>{
      const page:any=Object.create(Type.prototype);
      page.profile={ui_deferrals:{'source:s':{deferred:true,draft:{p:'Typed before leaving'}}}};
      page.sources=[{id:'s',kind:'uploaded_file',status:'ready',proposals:[{id:'p',status:'pending',field:'project_name',value:'Extracted name'}]}];
      expect(page.hasPendingReview).toBe(false);
      page.sources=page.prepareSources(page.sources);
      expect(page.sources[0].proposals[0].draftValue).toBe('Typed before leaving');
      page.profile.ui_deferrals['source:s'].deferred=false;
      expect(page.hasPendingReview).toBe(true);
      expect(page.sources[0].proposals[0].status).toBe('pending');
    });
  }
});
