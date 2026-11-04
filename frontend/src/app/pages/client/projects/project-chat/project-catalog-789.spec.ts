import '@angular/compiler';
import { describe, it, expect, vi, afterEach } from 'vitest';
import { Subject, of } from 'rxjs';
import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideRouter, ActivatedRoute } from '@angular/router';
import { ProjectChatComponent } from './project-chat';
import { ProjectOnboardingService } from './project-onboarding.service';
import { ProjectPropertyType, EMPTY_PROJECT_PROFILE } from './project-onboarding.models';
import { PROPERTY_TYPE_FIELDS, mergePropertyTypeDraft } from './property-type-form';
import { toPropertyTypePayload, validatePropertyType } from './project-form-validation';

function item(overrides: Partial<ProjectPropertyType> = {}): ProjectPropertyType {
  return {id:'type-1',project_id:'project-1',name:'Original',code:null,description:null,bedrooms:null,bathrooms:null,
    area_min:null,area_max:null,area_unit:null,total_units:null,available_units:null,starting_price:null,maximum_price:null,
    currency:null,features:[],inventory_updated_at:null,images_status:'pending',review_status:'confirmed',source_reference:null,
    sort_order:0,is_complete:true,media:[],created_at:'2026-01-01T00:00:00Z',updated_at:'2026-01-01T00:00:00Z',...overrides};
}
function setup(service: any = {}) {
  const component=new ProjectChatComponent({} as never,service,{detectChanges:vi.fn()} as never,{isSupported:false} as never,{} as never);
  component.projectId='project-1';
  component.propertyCatalog={items:[item()],confirmed_count:1,candidate_count:0,limit:20,remaining:19,catalog_complete:true};
  vi.spyOn(component as any,'syncState').mockImplementation(()=>undefined);
  return component;
}
const current=(component:ProjectChatComponent)=>component.propertyCatalog.items[0];
afterEach(()=>{vi.restoreAllMocks();TestBed.resetTestingModule();});

describe('Property catalog issues 7–9',()=>{
  it.each([null,0,4])('accepts quantity %s without a manually entered date',(available_units)=>{
    expect(validatePropertyType({name:'Type',available_units})).toEqual({});
    expect(toPropertyTypePayload({name:'Type',available_units,inventory_updated_at:'2026-01-01'})).not.toHaveProperty('inventory_updated_at');
  });
  it.each(['available_units','total_units','bathrooms','area_min','area_max','starting_price','maximum_price'] as const)('validates non-negative %s',(field)=>{
    expect(validatePropertyType({name:'Type',[field]:-1})).toHaveProperty(field);
  });
  it('does not invent numeric values, a currency or an area unit in a new type',()=>{
    const component=setup();
    for(const key of ['available_units','bedrooms','bathrooms','area_min','area_max','starting_price','currency','area_unit'] as const)expect(component.propertyTypeDraft[key]).toBeNull();
  });
  it('preserves all scalar edits when Add images later returns an old server row',()=>{
    const response=new Subject<ProjectPropertyType>();const component=setup({deferPropertyTypeImages:()=>response});
    Object.assign(current(component),{name:'Edited',bedrooms:2,description:'New description',available_units:0,features:['Balcony']});
    component.markPropertyTypeDirty(current(component));
    component.deferPropertyTypeImages(current(component));response.next(item({images_status:'deferred'}));response.complete();
    expect(current(component)).toMatchObject({name:'Edited',bedrooms:2,description:'New description',available_units:0,features:['Balcony'],images_status:'deferred'});
    expect(component.dirtyPropertyTypeIds.has('type-1')).toBe(true);
    expect(component.catalogReady).toBe(false);
  });
  it('keeps edits and a readable error when postponing images fails, then permits retry',()=>{
    let response=new Subject<ProjectPropertyType>();const component=setup({deferPropertyTypeImages:()=>response});
    current(component).name='Edited';component.markPropertyTypeDirty(current(component));
    component.deferPropertyTypeImages(current(component));response.error(new Error('network'));
    expect(component.errorMessage).toContain('changes remain');expect(component.isPropertyTypeSaving(current(component))).toBe(false);
    response=new Subject<ProjectPropertyType>();component.deferPropertyTypeImages(current(component));response.next(item({images_status:'deferred'}));response.complete();
    expect(current(component).name).toBe('Edited');
  });
  it('attaches media without replacing edits and does not drop newly selected images',()=>{
    const response=new Subject<ProjectPropertyType>();const component=setup({attachPropertyTypeMedia:()=>response});
    current(component).name='Edited';component.markPropertyTypeDirty(current(component));component.propertyTypeImageSelection.set('type-1',new Set(['image-1']));
    component.attachSelectedImages(current(component));component.togglePropertyTypeImage(current(component),'image-2');
    response.next(item({images_status:'provided',media:[{id:'m1',source_id:'image-1',caption:null,sort_order:0,image_url:'/image'}]}));response.complete();
    expect(current(component).name).toBe('Edited');expect(current(component).media).toHaveLength(1);
    expect([...component.propertyTypeImageSelection.get('type-1')!]).toEqual(['image-2']);
  });
  it('keeps failed image selection for retry without creating a second row',()=>{
    const response=new Subject<ProjectPropertyType>();const component=setup({attachPropertyTypeMedia:()=>response});
    current(component).name='Edited';component.markPropertyTypeDirty(current(component));component.propertyTypeImageSelection.set('type-1',new Set(['image-1']));
    component.attachSelectedImages(current(component));response.error(new Error('network'));
    expect(current(component).name).toBe('Edited');expect(component.propertyCatalog.items).toHaveLength(1);
    expect(component.propertyTypeImageSelection.get('type-1')?.has('image-1')).toBe(true);
  });
  it('merges server media on refresh while preserving dirty fields',()=>{
    const component=setup({getPropertyTypes:()=>of({items:[item({name:'Server',images_status:'provided',media:[{id:'m',source_id:'i',caption:null,sort_order:0,image_url:'/i'}]})],confirmed_count:1,candidate_count:0,limit:20,remaining:19})});
    current(component).name='Local edit';component.markPropertyTypeDirty(current(component));component.loadPropertyTypes();
    expect(current(component).name).toBe('Local edit');expect(current(component).media).toHaveLength(1);
  });
  it('ignores a catalog response started before the image mutation',()=>{
    const refresh=new Subject<any>();const image=new Subject<ProjectPropertyType>();const component=setup({getPropertyTypes:()=>refresh,deferPropertyTypeImages:()=>image});
    component.loadPropertyTypes();component.deferPropertyTypeImages(current(component));image.next(item({images_status:'deferred'}));image.complete();
    refresh.next({items:[item()],confirmed_count:1,candidate_count:0,limit:20,remaining:19});
    expect(current(component).images_status).toBe('deferred');
  });
  it('does not duplicate an image mutation while another mutation is pending',()=>{
    const response=new Subject<ProjectPropertyType>();const defer=vi.fn(()=>response);const attach=vi.fn(()=>response);
    const component=setup({deferPropertyTypeImages:defer,attachPropertyTypeMedia:attach});component.propertyTypeImageSelection.set('type-1',new Set(['i']));
    component.deferPropertyTypeImages(current(component));component.deferPropertyTypeImages(current(component));component.attachSelectedImages(current(component));
    expect(defer).toHaveBeenCalledOnce();expect(attach).not.toHaveBeenCalled();response.complete();
  });
  it('releases a timed-out image action without discarding the draft',()=>{
    vi.useFakeTimers();
    try {
      const component=setup({deferPropertyTypeImages:()=>new Subject<ProjectPropertyType>()});
      current(component).name='Pending changes';component.markPropertyTypeDirty(current(component));
      component.deferPropertyTypeImages(current(component));vi.advanceTimersByTime(20_001);
      expect(component.isPropertyTypeSaving(current(component))).toBe(false);
      expect(current(component).name).toBe('Pending changes');expect(component.errorMessage).toContain('changes remain');
    } finally {vi.useRealTimers();}
  });
  it('saves after an image deferral without resurrecting a stale Configure later draft',()=>{
    let request:any;const component=setup({deferPropertyTypeImages:()=>of(item({images_status:'deferred'})),updatePropertyType:(_p:string,_i:string,payload:any)=>{request=payload;return of(item({...payload,review_status:'confirmed'}));}});
    component.profile={...EMPTY_PROJECT_PROFILE,ui_deferrals:{'property:type-1':{deferred:false,draft:{name:'Stale persisted draft'}}}};
    current(component).name='Final edited name';component.markPropertyTypeDirty(current(component));component.deferPropertyTypeImages(current(component));component.confirmPropertyType(current(component));
    expect(request.name).toBe('Final edited name');expect(current(component).name).toBe('Final edited name');expect(component.dirtyPropertyTypeIds.size).toBe(0);
  });
  it('preserves edits made after a save request started',()=>{
    const response=new Subject<ProjectPropertyType>();const component=setup({updatePropertyType:()=>response});
    current(component).name='Submitted';component.markPropertyTypeDirty(current(component));component.confirmPropertyType(current(component));
    current(component).description='Changed during request';component.markPropertyTypeDirty(current(component));response.next(item({name:'Submitted'}));response.complete();
    expect(current(component).description).toBe('Changed during request');expect(component.dirtyPropertyTypeIds.has('type-1')).toBe(true);
  });
  it('does not add duplicate rows if creation is retried or refreshed',()=>{
    const response=new Subject<ProjectPropertyType>();const create=vi.fn(()=>response);const component=setup({createPropertyType:create});
    component.propertyTypeDraft={name:'New'};component.saveNewPropertyType();component.saveNewPropertyType();
    response.next(item());response.complete();expect(create).toHaveBeenCalledOnce();expect(component.propertyCatalog.items).toHaveLength(1);
  });
  it('uses a scalar whitelist so draft metadata cannot replace media, approval or confirmation',()=>{
    const merged=mergePropertyTypeDraft(item({images_status:'provided',inventory_updated_at:'2026-11-04',inventory_confirmed_by_user_id:'actor'}),{name:'Pending',images_status:'deferred',review_status:'candidate',inventory_updated_at:null,inventory_confirmed_by_user_id:'forged'});
    expect(merged).toMatchObject({name:'Pending',images_status:'provided',review_status:'confirmed',inventory_updated_at:'2026-11-04',inventory_confirmed_by_user_id:'actor'});
  });
  it('does not restore a stale persisted new-type draft over local edits during a state refresh',()=>{
    const component=setup();
    component.propertyTypeDraft.name='Local new type';component.markPropertyTypeDirty(component.propertyTypeDraft);
    const state={version:1,messages:[],profile:{...EMPTY_PROJECT_PROFILE,ui_deferrals:{'property:new':{deferred:false,draft:{name:'Old draft'}}}},stage:'conversation',sources:[],next_question:null};
    vi.spyOn(component,'loadPropertyTypes').mockImplementation(()=>undefined);
    vi.spyOn(component,'loadSalesAssets').mockImplementation(()=>undefined);
    (component as any).applyState(state);
    expect(component.propertyTypeDraft.name).toBe('Local new type');
  });
  it('restores the latest saved new-type draft once and preserves later changes',()=>{
    const component=setup();
    vi.spyOn(component,'loadPropertyTypes').mockImplementation(()=>undefined);
    vi.spyOn(component,'loadSalesAssets').mockImplementation(()=>undefined);
    const state={version:1,messages:[],profile:{...EMPTY_PROJECT_PROFILE,ui_deferrals:{'property:new':{deferred:false,draft:{name:'Latest'},updated_at:'2026-02-01'},'field:property_type_catalog':{deferred:false,draft:{newType:{name:'Older'}},updated_at:'2026-01-01'}}},stage:'conversation',sources:[],next_question:null};
    (component as any).applyState(state);expect(component.propertyTypeDraft.name).toBe('Latest');
    component.propertyTypeDraft.name='Modified locally';(component as any).applyState({...state,version:2});
    expect(component.propertyTypeDraft.name).toBe('Modified locally');
  });
  it('renders the identical field and image contract for extracted, saved and manual types',async()=>{
    vi.spyOn(ProjectChatComponent.prototype,'ngOnInit').mockImplementation(()=>undefined);
    TestBed.configureTestingModule({imports:[ProjectChatComponent],providers:[provideHttpClient(),provideRouter([]),{provide:ActivatedRoute,useValue:{snapshot:{paramMap:{get:()=>''},queryParamMap:{get:()=>null}}}}]});
    const fixture=TestBed.createComponent(ProjectChatComponent);const component=fixture.componentInstance;
    component.initialState='ready';component.showPropertyTypeForm=true;component.propertyCatalog={items:[item({review_status:'candidate'}),item({id:'type-2'})],confirmed_count:1,candidate_count:1,limit:20,remaining:19,catalog_complete:false};
    component.sources=[{id:'image-1',kind:'image',status:'ready',download_url:'/image',name:'Uploaded photo.png',proposals:[]} as any];
    component.sourceImageUrls.set('image-1','/preview');
    fixture.detectChanges();await fixture.whenStable();
    const forms=fixture.nativeElement.querySelectorAll('[data-testid="property-type-shared-fields"]');
    expect(forms.length).toBe(3);
    for(const form of forms)expect([...form.querySelectorAll('[data-property-field]')].map((field:any)=>field.getAttribute('data-property-field'))).toEqual(PROPERTY_TYPE_FIELDS.map(field=>field.key));
    for(const form of forms)expect(form.querySelector('img')?.getAttribute('alt')).toBe('Uploaded photo.png');
    forms[0].querySelector('button').click();forms[2].querySelector('button').click();
    expect(component.propertyTypeImageSelection.get('type-1')?.has('image-1')).toBe(true);
    expect(component.propertyTypeDraftImageSelection.has('image-1')).toBe(true);
    expect(fixture.nativeElement.querySelector('[data-testid="property-type-catalog"] input[type="date"]')).toBeNull();
    fixture.destroy();
  });
});
