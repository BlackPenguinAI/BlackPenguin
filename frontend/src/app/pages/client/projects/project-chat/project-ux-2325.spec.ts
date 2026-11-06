import '@angular/compiler';
import { afterEach,describe,it,expect,vi } from 'vitest';
import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting,HttpTestingController } from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';
import { of,Subject,throwError } from 'rxjs';
import { ReviewCardComponent } from '../../../../shared/ui/review-card';
import { ConfigureLaterComponent,questionCard,formatDraftSummary } from '../../../../shared/ui/configure-later/configure-later';
import { OnboardingLocationComponent } from '../../../../shared/ui/onboarding-location';
import { ProjectChatComponent } from './project-chat';
import { ProjectPropertyType,EMPTY_PROJECT_PROFILE } from './project-onboarding.models';
import { ChatComponent } from '../../../chat/chat';

function row():ProjectPropertyType {
  return {id:'type-1',project_id:'project-1',name:'My type',code:null,description:null,bedrooms:1,bathrooms:2,
    area_min:20,area_max:30,area_unit:'m²',total_units:null,available_units:0,starting_price:30000,maximum_price:null,
    currency:'USD',features:[],inventory_updated_at:null,images_status:'pending',review_status:'confirmed',source_reference:null,
    sort_order:0,is_complete:true,media:[],created_at:'2026-11-01',updated_at:'2026-11-01'};
}
function page(service:any={}) {
  const c=new ProjectChatComponent({} as any,service,{detectChanges:vi.fn()} as any,{isSupported:false} as any,{} as any);
  c.projectId='project-1';c.propertyCatalog={items:[row()],confirmed_count:1,candidate_count:0,limit:20,remaining:19,catalog_complete:true};
  vi.spyOn(c as any,'syncState').mockImplementation(()=>{});vi.spyOn(c,'loadSalesAssets').mockImplementation(()=>{});
  return c;
}
function fileEvent(file:File):Event {return {target:{files:[file],value:'selected'}} as any;}
const photo=()=>new File(['image bytes'],'photo.png',{type:'image/png'});
const source={id:'own-image',kind:'image',status:'ready',download_url:'/protected/file',name:'photo.png',proposals:[]} as any;
afterEach(()=>{vi.restoreAllMocks();vi.useRealTimers();TestBed.resetTestingModule();});

describe('Onboarding UX 23–25',()=>{
  it('renders a collapsed completed review and can expand without losing controls',async()=>{
    const fixture=TestBed.createComponent(ReviewCardComponent);
    fixture.componentRef.setInput('complete',true);fixture.componentRef.setInput('title','Saved type');fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('button').getAttribute('aria-expanded')).toBe('false');
    expect(fixture.nativeElement.querySelector('div').hidden).toBe(true);
    fixture.nativeElement.querySelector('button').click();fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('div').hidden).toBe(false);
    fixture.componentRef.setInput('revision','new revision');fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('div').hidden).toBe(true);
  });
  it('starts an unresolved review expanded',()=>{
    const f=TestBed.createComponent(ReviewCardComponent);f.detectChanges();expect(f.componentInstance.expanded).toBe(true);
  });
  it('keeps confirmed, dirty, candidate and resumed review states distinct',()=>{
    const c=page();const r=c.propertyCatalog.items[0];expect(c.propertyReviewComplete(r)).toBe(true);
    c.markPropertyTypeDirty(r);expect(c.propertyReviewComplete(r)).toBe(false);c.dirtyPropertyTypeIds.clear();
    r.review_status='candidate';expect(c.propertyReviewComplete(r)).toBe(false);r.review_status='confirmed';
    c.profile={...EMPTY_PROJECT_PROFILE,ui_deferrals:{'property:type-1':{deferred:false,resumed:true,draft:{}}}};
    expect(c.propertyReviewComplete(r)).toBe(false);
  });
  it('summarizes real zero quantities, area and currency without invented data',()=>{
    const c=page();expect(c.propertySummary(row())).toContain('Available: 0');
    expect(c.propertySummary({...row(),available_units:null})).toContain('not confirmed');
    expect(c.propertySummary(row())).toContain('30,000');
  });
  it.each([ProjectChatComponent,ChatComponent])('closes extraction after the final decision for %s',(Type)=>{
    const c:any=Object.create(Type.prototype);c.expandedSourceIds=new Set();
    const s={id:'s',status:'ready',proposals:[{status:'pending'}]};expect(c.isSourceExpanded(s)).toBe(true);
    s.proposals[0].status='confirmed';expect(c.isSourceExpanded(s)).toBe(false);
    c.onSourceToggle(s,{currentTarget:{open:true}});expect(c.isSourceExpanded(s)).toBe(true);
  });
  it('uploads a new private image without changing unsaved scalar fields',()=>{
    const upload=vi.fn(()=>of(source));const c=page({uploadPropertyImage:upload});const r=c.propertyCatalog.items[0];
    r.name='Pending name';c.markPropertyTypeDirty(r);vi.spyOn(c as any,'loadSourceImagePreviews').mockImplementation(()=>{});
    c.uploadPropertyImage(r,fileEvent(photo()));
    expect(upload).toHaveBeenCalledWith('project-1',expect.any(File),'internal',['gallery_image']);
    expect(r.name).toBe('Pending name');expect(c.dirtyPropertyTypeIds.has(r.id)).toBe(true);
    expect(c.propertyTypeImageSelection.get(r.id)?.has(source.id)).toBe(true);expect(r.media).toHaveLength(0);
    expect(c.sources[0].id).toBe(source.id);expect(c.selectedCoverSourceId).toBeNull();
  });
  it('preserves multiple image content types and requires separate lead approval',()=>{
    const upload=vi.fn(()=>of(source));const c=page({uploadPropertyImage:upload});vi.spyOn(c as any,'loadSourceImagePreviews').mockImplementation(()=>{});
    c.propertyImageSharing['new']='sales_candidate';c.toggleUploadTag({},'floor_plan');c.uploadPropertyImage({},fileEvent(photo()));
    expect(upload).toHaveBeenCalledWith('project-1',expect.any(File),'sales_candidate',['gallery_image','floor_plan']);
    expect(c.propertyTypeDraftImageSelection.has(source.id)).toBe(true);expect(c.salesAssets).toEqual([]);
  });
  it.each([new File(['x'],'bad.svg',{type:'image/svg+xml'}),new File([],'empty.png',{type:'image/png'})])('rejects an invalid image locally without clearing fields',(file)=>{
    const upload=vi.fn();const c=page({uploadPropertyImage:upload});c.propertyTypeDraft.name='Keep';
    c.uploadPropertyImage(c.propertyTypeDraft,fileEvent(file));expect(upload).not.toHaveBeenCalled();expect(c.propertyTypeDraft.name).toBe('Keep');expect(c.errorMessage).toContain('15 MB');
  });
  it('rejects oversize files and missing content types',()=>{
    const upload=vi.fn();const c=page({uploadPropertyImage:upload});const f=photo();Object.defineProperty(f,'size',{value:15*1024*1024+1});
    c.uploadPropertyImage({},fileEvent(f));c.propertyImageTags['new']=[];c.uploadPropertyImage({},fileEvent(photo()));expect(upload).not.toHaveBeenCalled();
  });
  it('keeps fields and selection after an upload fails and permits retry',()=>{
    const upload=vi.fn(()=>throwError(()=>new Error('network')));const c=page({uploadPropertyImage:upload});c.propertyTypeDraft.name='Keep';c.propertyTypeDraftImageSelection.add('old');
    c.uploadPropertyImage(c.propertyTypeDraft,fileEvent(photo()));expect(c.propertyTypeDraft.name).toBe('Keep');expect(c.propertyTypeDraftImageSelection.has('old')).toBe(true);
    expect(c.propertyImageUploads.size).toBe(0);expect(c.errorMessage).toContain('preserved');c.uploadPropertyImage(c.propertyTypeDraft,fileEvent(photo()));expect(upload).toHaveBeenCalledTimes(2);
  });
  it('blocks conflicting save, attachment and duplicate upload until completion',()=>{
    const pending=new Subject<any>();const upload=vi.fn(()=>pending);const update=vi.fn();const c=page({uploadPropertyImage:upload,updatePropertyType:update});
    c.uploadPropertyImage(c.propertyCatalog.items[0],fileEvent(photo()));c.uploadPropertyImage(c.propertyCatalog.items[0],fileEvent(photo()));c.confirmPropertyType(c.propertyCatalog.items[0]);
    expect(upload).toHaveBeenCalledOnce();expect(update).not.toHaveBeenCalled();expect(c.catalogReady).toBe(false);expect(c.catalogMutationBusy).toBe(true);
    pending.error(new Error('network'));expect(c.isPropertyTypeSaving(c.propertyCatalog.items[0])).toBe(false);expect(c.catalogMutationBusy).toBe(false);
  });
  it('releases stalled upload after timeout and retains draft',()=>{
    vi.useFakeTimers();const c=page({uploadPropertyImage:()=>new Subject()});c.propertyTypeDraft.name='Keep';
    c.uploadPropertyImage(c.propertyTypeDraft,fileEvent(photo()));vi.advanceTimersByTime(30_001);
    expect(c.propertyImageUploads.size).toBe(0);expect(c.propertyTypeDraft.name).toBe('Keep');
  });
  it('hides a new form after deferring and restores it on resume',()=>{
    const c=page();c.showPropertyTypeForm=true;c.propertyTypeDraft.name='Draft';
    c.deferralsSaved({'property:new':{deferred:true,draft:{name:'Draft'}}});expect(c.showPropertyTypeForm).toBe(false);
    c.deferralsSaved({'property:new':{deferred:false,resumed:true,draft:{name:'Draft'}}});expect(c.showPropertyTypeForm).toBe(true);expect(c.propertyTypeDraft.name).toBe('Draft');
  });
  it.each([['field:meta_connection_verified','meta_account'],['field:campaigns_defined','meta_assets'],['field:sales_contacts','team'],['field:property_type_catalog','catalog'],['documents','documents'],['field:country','location']])('resumes %s in its own editor task',(key,task)=>{
    const c=page();c.profile={...EMPTY_PROJECT_PROFILE,ui_deferrals:{[key]:{deferred:true,draft:{}}}};const open=vi.spyOn(c,'openEditorTask').mockImplementation(()=>{});
    c.deferralsSaved({[key]:{deferred:false,resumed:true,draft:{}}});expect(open).toHaveBeenCalledWith(task);
  });
  it('does not mislabel document tasks as final approval',()=>{
    expect(questionCard({input_type:'documents',field:null})).toBe('documents');expect(questionCard({input_type:'meta_task_choice'})).toBe('meta_setup');
  });
  it('keeps saved draft summary readable and hides technical scalar baselines',()=>{
    const text=formatDraftSummary({name:'Residence',details_base:{name:'Old'},selected_images:['a','b'],available_units:0});
    expect(text).toContain('Selected images: 2');expect(text).toContain('available units: 0');expect(text).not.toContain('details_base');expect(text).not.toContain('[object Object]');
  });
  it('keeps uploaded lead-sharing candidates visible for explicit approval',()=>{
    const c=page();expect(c.isReviewableSource(source)).toBe(false);
    c.salesAssets=[{source_id:source.id,approval_status:'draft'} as any];expect(c.isReviewableSource(source)).toBe(true);
    expect(c.salesAssets[0].approval_status).toBe('draft');
  });
  it('restores new-type image selections from the latest full-catalog draft only once',()=>{
    const c=page();vi.spyOn(c,'loadPropertyTypes').mockImplementation(()=>{});
    const state={version:1,messages:[],profile:{...EMPTY_PROJECT_PROFILE,ui_deferrals:{'field:property_type_catalog':{deferred:false,resumed:true,updated_at:'2026-11-01',draft:{newType:{name:'Saved new',selected_images:['own-image']}}}}},stage:'conversation',sources:[],next_question:null};
    (c as any).applyState(state);expect(c.propertyTypeDraft.name).toBe('Saved new');expect(c.propertyTypeDraftImageSelection.has('own-image')).toBe(true);
    c.propertyTypeDraftImageSelection.clear();(c as any).applyState({...state,version:2});expect(c.propertyTypeDraftImageSelection.size).toBe(0);
  });
  it('does not silently confirm the catalog while a selected image still needs association',()=>{
    const c=page();expect(c.catalogReady).toBe(true);c.propertyTypeImageSelection.set('type-1',new Set(['own-image']));expect(c.catalogReady).toBe(false);
    c.profile={...EMPTY_PROJECT_PROFILE,ui_deferrals:{'property:type-1':{deferred:true,draft:{selected_images:['own-image']}}}};
    expect(c.hasUnattachedImages).toBe(false);expect(c.propertyTypeImageSelection.get('type-1')?.has('own-image')).toBe(true);
  });
  it('blocks Configure later while a conflicting operation is active',()=>{
    TestBed.configureTestingModule({providers:[provideHttpClient(),provideHttpClientTesting()]});const f=TestBed.createComponent(ConfigureLaterComponent);const http=TestBed.inject(HttpTestingController);
    f.componentInstance.entityId='p';f.componentInstance.blocked=true;f.componentInstance.save();http.expectNone(()=>true);http.verify();
  });
  it('restores location draft without approving it or losing the current city',()=>{
    TestBed.configureTestingModule({providers:[provideHttpClient(),provideHttpClientTesting()]});const f=TestBed.createComponent(OnboardingLocationComponent);const http=TestBed.inject(HttpTestingController);
    f.componentInstance.entityId='p';f.componentInstance.records={'field:country':{deferred:false,resumed:true,draft:{country:'PE',city:'Lima',timezone:'America/Lima',entityId:'foreign'}}};
    f.detectChanges();http.expectOne(r=>r.url.endsWith('/project/p/location')).flush({country:'US',city:'Miami',timezone:'America/New_York',countries:[],cities:[]});
    expect(f.componentInstance.city).toBe('Lima');expect(f.componentInstance.entityId).toBe('p');http.expectNone(r=>r.method==='POST');http.verify();
  });
  it('renders upload inside each type even with no extracted images',async()=>{
    vi.spyOn(ProjectChatComponent.prototype,'ngOnInit').mockImplementation(()=>{});
    TestBed.configureTestingModule({imports:[ProjectChatComponent],providers:[provideHttpClient(),provideRouter([])]});
    const f=TestBed.createComponent(ProjectChatComponent);const c=f.componentInstance;c.initialState='ready';c.showPropertyTypeForm=true;
    c.propertyCatalog={items:[row()],confirmed_count:1,candidate_count:0,limit:20,remaining:19,catalog_complete:false};f.detectChanges();await f.whenStable();
    expect(f.nativeElement.querySelectorAll('[data-testid="property-image-upload"] input[type="file"]').length).toBe(2);
    expect(f.nativeElement.querySelector('[data-testid="property-image-upload"] select').value).toBe('internal');
    const cards=f.nativeElement.querySelectorAll('[data-testid="property-type-catalog"] app-review-card');expect(cards.length).toBe(1);
    expect(cards[0].querySelector('button').getAttribute('aria-expanded')).toBe('false');cards[0].querySelector('button').click();f.detectChanges();
    expect(cards[0].querySelector('input[type="file"]')).not.toBeNull();f.destroy();
  });
});
