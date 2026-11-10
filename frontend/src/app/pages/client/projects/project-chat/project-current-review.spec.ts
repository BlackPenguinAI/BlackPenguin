import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActivatedRoute, provideRouter, Router } from '@angular/router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ProjectChatComponent } from './project-chat';
import { EMPTY_PROJECT_PROFILE, ProjectPropertyType, ProjectSalesAsset } from './project-onboarding.models';

const type = (): ProjectPropertyType => ({id:'type-1',project_id:'project-1',name:'Residence',code:null,description:'Saved details',bedrooms:2,bathrooms:1,area_min:80,area_max:80,area_unit:'m²',total_units:5,available_units:2,starting_price:100,maximum_price:100,currency:'USD',features:[],media:[],images_status:'deferred',review_status:'confirmed',updated_at:'2026-11-09T00:00:00Z',sort_order:0} as unknown as ProjectPropertyType);
const pdf = (): ProjectSalesAsset => ({id:'pdf-1',property_type_id:'type-1',source_id:'source-1',mime_type:'application/pdf',display_name:'Floor plan',content_tags:['floor_plan'],allowed_channels:['sms'],approval_status:'draft',extracted_links:[],version:1} as unknown as ProjectSalesAsset);
const approvalMessage = () => ({id:'old-review',sender:'ai',content:'Review the Project Profile',created_at:'2026-11-01T00:00:00Z',attachments:[],ui_payload:{field:null,label:'Final approval',input_type:'boolean',answer_actions:{'Approve profile':{kind:'approve_profile'}}}} as never);

describe('Current Project review and stable property editor', () => {
  let fixture: ComponentFixture<ProjectChatComponent>;
  let component: ProjectChatComponent;
  let http: HttpTestingController;
  beforeEach(async () => {
    vi.spyOn(ProjectChatComponent.prototype,'ngOnInit').mockImplementation(() => undefined);
    await TestBed.configureTestingModule({imports:[ProjectChatComponent],providers:[provideHttpClient(),provideHttpClientTesting(),provideRouter([]),{provide:ActivatedRoute,useValue:{snapshot:{paramMap:{get:()=> 'project-1'},queryParamMap:{get:()=>null}}}}]}).compileComponents();
    fixture=TestBed.createComponent(ProjectChatComponent);component=fixture.componentInstance;
    http=TestBed.inject(HttpTestingController);
    component.projectId='project-1';component.initialState='ready';component.showWelcome=false;
    component.profile={...EMPTY_PROJECT_PROFILE,completion:{...EMPTY_PROJECT_PROFILE.completion,required_fields_complete:true,ready_for_confirmation:true,final_approved:false,draft_revision:4}};
  });
  afterEach(() => {http.verify();TestBed.resetTestingModule();});

  it('renders one current approval after the catalog and makes historical prompts read-only', () => {
    component.messages=[approvalMessage(),{...approvalMessage() as any,id:'another-old-review'}];
    component.catalogEditorOpen=true;
    component.propertyCatalog={...component.propertyCatalog,items:[type()],confirmed_count:1};
    fixture.detectChanges();
    const root=fixture.nativeElement as HTMLElement;
    expect(root.querySelectorAll('[data-testid="historical-final-review"]')).toHaveLength(2);
    expect(root.querySelector('[data-testid="historical-final-review"] button')).toBeNull();
    const current=root.querySelector('[data-testid="current-final-review"]')!;
    const catalog=root.querySelector('[data-testid="property-type-catalog"]')!;
    expect(catalog.compareDocumentPosition(current)&Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    const approve=Array.from(current.querySelectorAll('button')).find(button=>button.textContent?.trim()==='Approve profile')!;
    expect(approve.disabled).toBe(true);
    component.catalogEditorOpen=false;fixture.changeDetectorRef.markForCheck();fixture.detectChanges();
    expect(root.querySelectorAll('[data-testid="current-final-review"]')).toHaveLength(1);
    expect(approve.disabled).toBe(false);
  });

  it('preserves the property card, disclosure, focused control and dirty draft across a server refresh', () => {
    component.catalogEditorOpen=true;component.selectedPropertyId='type-1';
    component.propertyCatalog={...component.propertyCatalog,items:[type()],confirmed_count:1};
    component.propertyReviewOpen.set('type-1',true);
    component.propertyCatalog.items[0].description='My unsaved draft';
    component.dirtyPropertyTypeIds.add('type-1');
    fixture.detectChanges();
    const card=fixture.nativeElement.querySelector('[data-property-id="type-1"]');
    const input=card.querySelector('input:not([type="file"]):not([type="checkbox"])') as HTMLInputElement;
    input.focus();
    component.loadPropertyTypes();
    http.expectOne(request=>request.url.endsWith('/property-types')).flush({...component.propertyCatalog,items:[{...type(),updated_at:'2026-11-09T01:00:00Z'}]});
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('[data-property-id="type-1"]')).toBe(card);
    expect(document.activeElement).toBe(input);
    expect(component.propertyReviewIsOpen(component.propertyCatalog.items[0])).toBe(true);
    expect(component.propertyCatalog.items[0].description).toBe('My unsaved draft');
    expect(component.selectedPropertyId).toBe('type-1');
  });

  it('saves lead access without resaving property details and keeps the editor open', () => {
    vi.spyOn(component as any,'syncState').mockImplementation(() => undefined);
    component.catalogEditorOpen=true;component.propertyReviewOpen.set('type-1',true);
    component.propertyCatalog={...component.propertyCatalog,items:[type()],confirmed_count:1};
    component.salesAssets=[pdf()];
    component.approveSalesAsset(pdf());
    http.expectOne(request=>request.url.endsWith('/sales-assets/pdf-1/approve')).flush({...pdf(),approval_status:'approved',resource_url:'https://example.com/public'});
    http.expectNone(request=>request.method==='PUT');
    expect(component.propertyDetailsNeedSave(component.propertyCatalog.items[0])).toBe(false);
    expect(component.propertyReviewIsOpen(component.propertyCatalog.items[0])).toBe(true);
    expect(component.resourceMessages.get('pdf-1')).toContain('Lead access saved');
  });

  it('confirms the catalog, closes that editor and refreshes the final review at the bottom', () => {
    const sync=vi.spyOn(component as any,'syncState').mockImplementation(() => undefined);
    component.catalogEditorOpen=true;component.selectedPropertyId='type-1';
    component.propertyCatalog={...component.propertyCatalog,items:[type()],confirmed_count:1};
    component.confirmPropertyCatalog();
    http.expectOne(request=>request.url.endsWith('/property-types/confirm')).flush({...component.propertyCatalog,catalog_complete:true});
    expect(component.catalogEditorOpen).toBe(false);expect(component.selectedPropertyId).toBe('');
    expect(sync).toHaveBeenCalledWith('bottom');
  });

  it('submits the visible revision once and redirects after success', () => {
    const navigate=vi.spyOn(TestBed.inject(Router),'navigateByUrl').mockResolvedValue(true);
    component.completeOnboarding();component.completeOnboarding();
    const request=http.expectOne(request=>request.url.endsWith('/onboarding/complete'));
    expect(request.request.body).toEqual({expected_revision:4});
    request.flush({completed:true,redirect_url:'/app/projects/project-1',profile:{...component.profile,completion:{...component.profile.completion,final_approved:true}}});
    expect(navigate).toHaveBeenCalledExactlyOnceWith('/app/projects/project-1');
    expect(component.isCompleting).toBe(false);
  });

  it('does not submit any historical approval and reloads a stale current review without navigating', () => {
    const sync=vi.spyOn(component as any,'syncState').mockImplementation(() => undefined);
    const navigate=vi.spyOn(TestBed.inject(Router),'navigateByUrl').mockResolvedValue(true);
    component.messages=[approvalMessage()];component.chooseAnswer('Approve profile',component.messages[0]);
    http.expectNone(request=>request.url.endsWith('/onboarding/complete'));
    component.completeOnboarding();
    http.expectOne(request=>request.url.endsWith('/onboarding/complete')).flush({detail:{message:'Review the current revision before approving.'}},{status:409,statusText:'Conflict'});
    expect(sync).toHaveBeenCalledWith('preserve');expect(navigate).not.toHaveBeenCalled();
    expect(component.isCompleting).toBe(false);
  });

  it('blocks approval while gallery access or property details are unsaved', () => {
    component.propertyCatalog={...component.propertyCatalog,items:[type()],confirmed_count:1};
    component.propertyGalleryAccess['type-1']=true;
    expect(component.approvalUiBlocked).toBe(true);expect(component.catalogReady).toBe(false);
    component.completeOnboarding();http.expectNone(request=>request.url.endsWith('/onboarding/complete'));
  });

  it('shows a return action for an already approved profile without asking for another approval', () => {
    component.profile.completion.final_approved=true;fixture.detectChanges();
    const current=fixture.nativeElement.querySelector('[data-testid="current-final-review"]');
    expect(current.textContent).toContain('Return to Project summary');
    expect(current.textContent).not.toContain('Approve profile');
    component.completeOnboarding();http.expectNone(request=>request.url.endsWith('/onboarding/complete'));
  });
});
