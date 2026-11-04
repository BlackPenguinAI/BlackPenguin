import '@angular/compiler';
import { it, expect, vi } from 'vitest';
import { propertyTypeDetails, restorePropertyTypeDraft } from './property-type-form';
import { of, Subject } from 'rxjs';
import { ProjectChatComponent } from './project-chat';
import { ProjectPropertyType, EMPTY_PROJECT_PROFILE } from './project-onboarding.models';

function saved(): ProjectPropertyType {
  return {id:'type-1',project_id:'project-1',name:'Server name',code:null,description:null,bedrooms:null,bathrooms:null,
    area_min:null,area_max:null,area_unit:null,total_units:null,available_units:null,starting_price:null,maximum_price:null,
    currency:null,features:[],inventory_updated_at:null,images_status:'deferred',review_status:'confirmed',source_reference:null,
    sort_order:0,is_complete:true,media:[],created_at:'2026-11-01T10:00:00Z',updated_at:'2026-11-01T11:00:00Z'};
}
function component(service: any) {
  const c=new ProjectChatComponent({} as never,service,{detectChanges:vi.fn()} as never,{isSupported:false} as never,{} as never);
  c.projectId='project-1';vi.spyOn(c as any,'syncState').mockImplementation(()=>undefined);
  return c;
}

it('recovers if attaching images never responds after a successful property creation',()=>{
  vi.useFakeTimers();
  try {
    const c=component({createPropertyType:()=>of(saved()),attachPropertyTypeMedia:()=>new Subject<ProjectPropertyType>()});
    c.propertyTypeDraft={name:'New type'};c.propertyTypeDraftImageSelection.add('image-1');
    c.saveNewPropertyType();vi.advanceTimersByTime(20_001);
    expect(c.creatingPropertyType).toBe(false);
    expect(c.propertyCatalog.items.some(row=>row.id==='type-1')).toBe(true);
    expect(c.propertyTypeImageSelection.get('type-1')?.has('image-1')).toBe(true);
  } finally {vi.useRealTimers();vi.restoreAllMocks();}
});

it('restores a saved scalar draft when only the image state changed after it was deferred',()=>{
  const c=component({getPropertyTypes:()=>of({items:[saved()],confirmed_count:1,candidate_count:0,remaining:19,limit:20,catalog_complete:false})});
  c.profile={...EMPTY_PROJECT_PROFILE,ui_deferrals:{'property:type-1':{deferred:false,resumed:true,updated_at:'2026-11-01T10:30:00Z',draft:{name:'Saved pending name',description:'Saved pending description',selected_images:['image-1']}}}};
  c.loadPropertyTypes();
  expect(c.propertyCatalog.items[0].name).toBe('Saved pending name');
  expect(c.propertyCatalog.items[0].description).toBe('Saved pending description');
  expect(c.dirtyPropertyTypeIds.has('type-1')).toBe(true);
  vi.restoreAllMocks();
});

it('keeps a new scalar baseline stable when local feature arrays are edited',()=>{
  const row=saved();row.features=['Garden'];const base=propertyTypeDetails(row);
  row.features.push('Balcony');expect(base['features']).toEqual(['Garden']);
});

it('restores a new-format draft after image-only changes but not after real scalar changes',()=>{
  const row=saved();const draft={name:'Pending',details_base:propertyTypeDetails(row)};
  expect(restorePropertyTypeDraft({...row,images_status:'provided',updated_at:'2026-12-01'},draft,{resumed:true})).toBe(true);
  expect(restorePropertyTypeDraft({...row,name:'Changed by another editor'},draft,{resumed:true})).toBe(false);
  expect(restorePropertyTypeDraft(row,draft,{completed_at:'2026-12-01'})).toBe(false);
});

it('preserves a full catalog draft after an image-only update when returning to onboarding',()=>{
  const c=component({getPropertyTypes:()=>of({items:[saved()],confirmed_count:1,candidate_count:0,remaining:19,limit:20})});
  c.profile={...EMPTY_PROJECT_PROFILE,ui_deferrals:{'field:property_type_catalog':{deferred:false,resumed:true,updated_at:'2026-11-01T10:30:00Z',draft:{items:[{id:'type-1',name:'Whole catalog pending name',details_base:propertyTypeDetails(saved())}]}}}};
  c.loadPropertyTypes();expect(c.propertyCatalog.items[0].name).toBe('Whole catalog pending name');
  expect((c.cardDraft('property_type_catalog') as any).items[0].details_base).toEqual(propertyTypeDetails(saved()));
  vi.restoreAllMocks();
});

it('does not resurrect a consumed legacy draft during a late catalog refresh after saving',()=>{
  const row=saved();const service={getPropertyTypes:()=>of({items:[row],confirmed_count:1,candidate_count:0,remaining:19,limit:20}),updatePropertyType:(_p:any,_i:any,payload:any)=>{Object.assign(row,payload);return of({...row});}};
  const c=component(service);
  c.profile={...EMPTY_PROJECT_PROFILE,ui_deferrals:{'property:type-1':{resumed:true,deferred:false,draft:{name:'Old pending name'}}}};
  c.loadPropertyTypes();c.propertyCatalog.items[0].name='Final saved name';c.markPropertyTypeDirty(c.propertyCatalog.items[0]);
  c.confirmPropertyType(c.propertyCatalog.items[0]);c.loadPropertyTypes();
  expect(c.propertyCatalog.items[0].name).toBe('Final saved name');
  vi.restoreAllMocks();
});

it('retains the created row and image selection after an image error, then retries without another create',()=>{
  const pending=new Subject<ProjectPropertyType>();let fail=true;
  const create=vi.fn(()=>of(saved()));const attach=vi.fn(()=>fail ? pending : of({...saved(),images_status:'provided' as const}));
  const c=component({createPropertyType:create,attachPropertyTypeMedia:attach});
  c.propertyTypeDraft={name:'New'};c.propertyTypeDraftImageSelection.add('image-1');c.saveNewPropertyType();pending.error(new Error('network'));
  expect(c.creatingPropertyType).toBe(false);expect(c.propertyCatalog.items).toHaveLength(1);
  expect(c.propertyTypeImageSelection.get('type-1')?.has('image-1')).toBe(true);
  fail=false;c.attachSelectedImages(c.propertyCatalog.items[0]);
  expect(create).toHaveBeenCalledOnce();expect(attach).toHaveBeenCalledTimes(2);expect(c.propertyCatalog.items).toHaveLength(1);
  expect(c.propertyCatalog.items[0].images_status).toBe('provided');
  vi.restoreAllMocks();
});
