import '@angular/compiler';
import { it,expect,vi,afterEach } from 'vitest';
import { of } from 'rxjs';
import { ProjectChatComponent } from './project-chat';
import { EMPTY_PROJECT_PROFILE, ProjectPropertyType } from './project-onboarding.models';
import { propertyTypeDetails } from './property-type-form';
import { Component } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { FormsModule } from '@angular/forms';
import { ReviewCardComponent } from '../../../../shared/ui/review-card';

function row():ProjectPropertyType {
  return {id:'unit',project_id:'project',name:'Original',code:null,description:null,bedrooms:null,bathrooms:null,
    area_min:null,area_max:null,area_unit:null,total_units:null,available_units:null,starting_price:null,maximum_price:null,
    currency:null,features:[],inventory_updated_at:null,images_status:'pending',review_status:'confirmed',source_reference:null,
    sort_order:0,is_complete:true,media:[],created_at:'2026-11-01',updated_at:'2026-11-01'};
}
function page(records:any) {
  const component=new ProjectChatComponent({} as any,{getPropertyTypes:()=>of({items:[row()],confirmed_count:1,candidate_count:0,limit:20,remaining:19,catalog_complete:false})} as any,{detectChanges:vi.fn()} as any,{isSupported:false} as any,{} as any);
  component.projectId='project';component.profile={...EMPTY_PROJECT_PROFILE,ui_deferrals:records};return component;
}
afterEach(()=>{vi.restoreAllMocks();TestBed.resetTestingModule();});

it('restores selected images for an EXISTING type after deferring the whole catalog and reloading',()=>{
  const component=page({'field:property_type_catalog':{deferred:false,resumed:true,updated_at:'2026-11-05T10:00:00Z',draft:{items:[{...row(),details_base:propertyTypeDetails(row()),selected_images:['uploaded-photo']}]}}});
  component.loadPropertyTypes();
  expect([...component.propertyTypeImageSelection.get('unit') || []]).toEqual(['uploaded-photo']);
  expect(component.hasUnattachedImages).toBe(true);
});

it('gives the newer catalog draft precedence over an older resumed per-type draft',()=>{
  const component=page({
    'property:unit':{deferred:false,resumed:true,updated_at:'2026-11-05T09:00:00Z',draft:{name:'Older name',details_base:propertyTypeDetails(row()),selected_images:['old-photo']}},
    'field:property_type_catalog':{deferred:false,resumed:true,updated_at:'2026-11-05T10:00:00Z',draft:{items:[{...row(),name:'Latest name',details_base:propertyTypeDetails(row()),selected_images:['latest-photo']}]}}
  });
  component.loadPropertyTypes();
  expect(component.propertyCatalog.items[0].name).toBe('Latest name');
  expect([...component.propertyTypeImageSelection.get('unit') || []]).toEqual(['latest-photo']);
});

it('does not replace an active local image choice during a catalog refresh',()=>{
  const component=page({'property:unit':{deferred:false,resumed:true,draft:{selected_images:['old-photo']}}});
  component.propertyTypeImageSelection.set('unit',new Set(['local-photo']));component.loadPropertyTypes();
  expect([...component.propertyTypeImageSelection.get('unit') || []]).toEqual(['local-photo']);
});

it('does not override newer saved scalar facts with a baseline-conflicting draft',()=>{
  const component=page({'property:unit':{deferred:false,resumed:true,draft:{name:'Old draft',details_base:{...propertyTypeDetails(row()),name:'Older server version'}}}});
  component.loadPropertyTypes();expect(component.propertyCatalog.items[0].name).toBe('Original');
});

@Component({standalone:true,imports:[ReviewCardComponent,FormsModule],template:`<app-review-card title="Review" status="Pending"><input [(ngModel)]="draft"></app-review-card>`})
class DraftHost {draft='Original';}
it('collapsing and reopening preserves the projected input node and unsaved data',async()=>{
  const fixture=TestBed.createComponent(DraftHost);fixture.detectChanges();await fixture.whenStable();
  const input=fixture.nativeElement.querySelector('input');input.value='Unsaved detail';input.dispatchEvent(new Event('input'));fixture.detectChanges();await fixture.whenStable();
  const toggle=fixture.nativeElement.querySelector('button');toggle.click();fixture.detectChanges();
  expect(fixture.nativeElement.querySelector('input')).toBe(input);expect(input.value).toBe('Unsaved detail');
  expect(toggle.getAttribute('aria-expanded')).toBe('false');toggle.click();fixture.detectChanges();
  expect(input.value).toBe('Unsaved detail');expect(fixture.componentInstance.draft).toBe('Unsaved detail');
});

function records(catalogAt:string|undefined,rowAt:string|undefined,selected:any[]=['catalog-photo']) {
  return {
    'field:property_type_catalog':{deferred:false,resumed:true,updated_at:catalogAt,draft:{items:[{...row(),name:'Catalog name',details_base:propertyTypeDetails(row()),selected_images:selected}]}},
    'property:unit':{deferred:false,resumed:true,updated_at:rowAt,draft:{name:'Per-type name',details_base:propertyTypeDetails(row()),selected_images:['row-photo']}}
  };
}
it('gives a newer per-type draft precedence over the full catalog for fields AND images',()=>{
  const component=page(records('2026-11-05T09:00:00Z','2026-11-05T10:00:00Z'));component.loadPropertyTypes();
  expect(component.propertyCatalog.items[0].name).toBe('Per-type name');expect([...component.propertyTypeImageSelection.get('unit') || []]).toEqual(['row-photo']);
});
it('honors an explicit empty image selection in the newer snapshot',()=>{
  const component=page(records('2026-11-05T10:00:00Z','2026-11-05T09:00:00Z',[]));component.loadPropertyTypes();
  expect(component.propertyCatalog.items[0].name).toBe('Catalog name');expect([...component.propertyTypeImageSelection.get('unit') || []]).toEqual([]);
});
it('preserves explicit local deselection across background refresh',()=>{
  const component=page(records('2026-11-05T10:00:00Z','2026-11-05T09:00:00Z'));component.propertyTypeImageSelection.set('unit',new Set());component.loadPropertyTypes();
  expect(component.propertyTypeImageSelection.get('unit')?.size).toBe(0);
});
it('keeps deterministic legacy precedence when neither snapshot has a date',()=>{
  const component=page(records(undefined,undefined));component.loadPropertyTypes();expect(component.propertyCatalog.items[0].name).toBe('Per-type name');
});
it('compares timezone offsets with server UTC timestamps consistently',()=>{
  const component=page(records('2026-11-05T12:00:00.000000','2026-11-05T07:30:00-05:00'));component.loadPropertyTypes();
  expect(component.propertyCatalog.items[0].name).toBe('Per-type name');
});
it('preserves sub-millisecond ordering from server deferral timestamps',()=>{
  const component=page(records('2026-11-05T12:00:00.000002','2026-11-05T12:00:00.000001'));component.loadPropertyTypes();
  expect(component.propertyCatalog.items[0].name).toBe('Catalog name');
});
it('does not restore image selections from a completed draft',()=>{
  const saved:any=records('2026-11-05T09:00:00Z','2026-11-05T10:00:00Z');saved['property:unit'].completed_at='2026-11-05T11:00:00Z';
  const component=page(saved);component.loadPropertyTypes();expect([...component.propertyTypeImageSelection.get('unit') || []]).toEqual(['catalog-photo']);
});
it('does not restore image selections from a baseline-conflicting draft',()=>{
  const component=page({'property:unit':{deferred:false,resumed:true,draft:{name:'Old',selected_images:['stale'],details_base:{...propertyTypeDetails(row()),name:'Previous saved name'}}}});
  component.loadPropertyTypes();expect(component.propertyTypeImageSelection.has('unit')).toBe(false);
});
it('does not restore a consumed catalog selection after saving a row',()=>{
  const saved=records('2026-11-05T10:00:00Z','2026-11-05T09:00:00Z');const component=page(saved);
  (component as any).consumedPropertyDrafts.set('unit:field:property_type_catalog',JSON.stringify(saved['field:property_type_catalog']));
  (component as any).consumedPropertyDrafts.set('unit:property:unit',JSON.stringify(saved['property:unit']));component.loadPropertyTypes();
  expect(component.propertyTypeImageSelection.has('unit')).toBe(false);expect(component.propertyCatalog.items[0].name).toBe('Original');
});
it('keeps already attached images out of pending selections',()=>{
  const component=page(records('2026-11-05T10:00:00Z','2026-11-05T09:00:00Z'));
  const restored=(component as any).normalizePropertyType({...row(),media:[{source_id:'catalog-photo'}]});
  expect(restored.media[0].source_id).toBe('catalog-photo');expect(component.propertyTypeImageSelection.get('unit')?.size).toBe(0);
});
it('restores only valid unique image identifiers without trusting draft metadata',()=>{
  const component=page(records('2026-11-05T10:00:00Z','2026-11-05T09:00:00Z',['photo','photo',null,1,{},'']));component.loadPropertyTypes();
  expect([...component.propertyTypeImageSelection.get('unit') || []]).toEqual(['photo']);
  expect(component.propertyCatalog.items[0].review_status).toBe('confirmed');expect(component.propertyCatalog.items[0].media).toEqual([]);
});
it('uses the same precise priority for a new type and its full-catalog draft',()=>{
  const component=page({
    'property:new':{deferred:false,resumed:true,updated_at:'2026-11-05T12:00:00.000001',draft:{name:'Older new type',selected_images:['old']}},
    'field:property_type_catalog':{deferred:false,resumed:true,updated_at:'2026-11-05T12:00:00.000002',draft:{newType:{name:'Latest new type',selected_images:[]}}}
  });
  vi.spyOn(component,'loadPropertyTypes').mockImplementation(()=>{});vi.spyOn(component,'loadSalesAssets').mockImplementation(()=>{});
  (component as any).applyState({version:1,messages:[],profile:component.profile,stage:'conversation',sources:[],next_question:null});
  expect(component.propertyTypeDraft.name).toBe('Latest new type');expect(component.propertyTypeDraftImageSelection.size).toBe(0);
});
