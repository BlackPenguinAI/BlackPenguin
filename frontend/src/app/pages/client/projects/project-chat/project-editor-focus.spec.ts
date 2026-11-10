import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting,HttpTestingController } from '@angular/common/http/testing';
import { TestBed, ComponentFixture } from '@angular/core/testing';
import { provideRouter,ActivatedRoute } from '@angular/router';
import { afterEach,beforeEach,describe,it,expect,vi } from 'vitest';
import { ProjectChatComponent } from './project-chat';
import { EMPTY_PROJECT_PROFILE } from './project-onboarding.models';

const question=(task:string)=>({task,field:task==='catalog'?'property_type_catalog':task==='location'?'country':'delivery_dates',input_type:task==='catalog'?'property_type_catalog':task==='location'?'location_editor':'detail_editor',label:task,prompt:'Review',options:[],examples:[],allow_custom:false,minimum_words:null});
const turn=(task:string,revision:number)=>({message:{id:'question-'+revision,sender:'ai',created_at:'2026-11-09',content:'Review',ui_payload:question(task)},profile:{...EMPTY_PROJECT_PROFILE,ui_deferrals:{__editor_focus__:{deferred:false,draft:{active_task:task,revision}}}},sources:[],next_question:question(task)});

describe('Exclusive editor navigation',()=>{
 let c:ProjectChatComponent,http:HttpTestingController,fixture:ComponentFixture<ProjectChatComponent>;
 beforeEach(async()=>{
  vi.spyOn(ProjectChatComponent.prototype,'ngOnInit').mockImplementation(()=>undefined);
  await TestBed.configureTestingModule({imports:[ProjectChatComponent],providers:[provideHttpClient(),provideHttpClientTesting(),provideRouter([]),{provide:ActivatedRoute,useValue:{snapshot:{paramMap:{get:()=> 'project'},queryParamMap:{get:()=>null}}}}]}).compileComponents();
  fixture=TestBed.createComponent(ProjectChatComponent);c=fixture.componentInstance;c.projectId='project';http=TestBed.inject(HttpTestingController);
  vi.spyOn(c,'loadPropertyTypes').mockImplementation(()=>undefined);vi.spyOn(c as any,'loadSalesAssets').mockImplementation(()=>undefined);
 });
 afterEach(()=>{try{http.verify();}finally{TestBed.resetTestingModule();}});
 it('serializes rapid clicks and opens only the final requested destination',()=>{
  c.openEditorTask('catalog');c.openEditorTask('location');c.openEditorTask('delivery');
  http.expectNone(r=>r.url.endsWith('/editor/location'));
  http.expectOne(r=>r.url.endsWith('/editor/catalog')).flush(turn('catalog',1));
  const next=http.expectOne(r=>r.url.endsWith('/editor/delivery'));
  expect(next.request.body.transition.from_task).toBe('catalog');expect(next.request.body.transition.expected_navigation_revision).toBe(1);
  next.flush(turn('delivery',2));
  expect(c.activeEditorTask).toBe('delivery');expect(c.catalogEditorOpen).toBe(false);expect(c.showPropertyCatalog).toBe(false);
 });
 it('keeps the current editor and dirty fields when the transition fails',()=>{
  c.activeEditorTask='catalog';c.catalogEditorOpen=true;c.profile=turn('catalog',1).profile as never;
  c.dirtyPropertyTypeIds.add('type-1');c.openEditorTask('location');
  const request=http.expectOne(r=>r.url.endsWith('/editor/location'));
  expect(request.request.body.transition.changed).toBe(true);
  request.flush({detail:'Retry the switch.'},{status:503,statusText:'Unavailable'});
  expect(c.activeEditorTask).toBe('catalog');expect(c.catalogEditorOpen).toBe(true);expect(c.dirtyPropertyTypeIds.has('type-1')).toBe(true);
  expect(c.editorNavigationBusy).toBe(false);expect(c.errorMessage).toContain('Retry');
 });
 it('reuses the same idempotency key after a network failure',()=>{
  c.openEditorTask('location');const first=http.expectOne(r=>r.url.endsWith('/editor/location'));
  const id=first.request.body.client_message_id;
  first.flush({}, {status:0,statusText:'Network failure'});
  c.openEditorTask('location');const retry=http.expectOne(r=>r.url.endsWith('/editor/location'));
  expect(retry.request.body.client_message_id).toBe(id);retry.flush(turn('location',1));
 });
 it('captures an unapproved location draft and never posts profile facts on navigation',()=>{
  c.activeEditorTask='location';c.profile=turn('location',1).profile as never;
  c.locationEditors={first:{editorDraft:{country:'US',city:'My draft city',timezone:'America/New_York'},draftChanged:true},some:()=>false} as never;
  c.openEditorTask('delivery');const request=http.expectOne(r=>r.url.endsWith('/editor/delivery'));
  expect(request.request.body.transition.draft.city).toBe('My draft city');expect(request.request.body.transition.changed).toBe(true);
  http.expectNone(r=>r.url.endsWith('/profile'));request.flush(turn('delivery',2));
 });
 it('reselects the current editor without duplicating a server turn',()=>{
  c.activeEditorTask='catalog';c.openEditorTask('catalog');http.expectNone(r=>r.method==='POST');
 });
 it('uses scoped scrolling and keeps pending file objects selected',()=>{
  c.selectedFiles=[new File(['pdf'],'draft.pdf',{type:'application/pdf'})];c.openEditorTask('location');
  expect(c.selectedFiles).toHaveLength(1);http.expectNone(r=>r.method==='POST');
 });
 it('waits for a save to finish and retains the last queued target',()=>{
  vi.useFakeTimers();c.salesAssetBusy=true;c.openEditorTask('location');c.openEditorTask('delivery');
  http.expectNone(r=>r.method==='POST');c.salesAssetBusy=false;vi.advanceTimersByTime(151);
  http.expectOne(r=>r.url.endsWith('/editor/delivery')).flush(turn('delivery',1));
  expect(c.activeEditorTask).toBe('delivery');vi.clearAllTimers();vi.useRealTimers();
 });
});
