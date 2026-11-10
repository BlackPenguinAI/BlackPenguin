import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActivatedRoute, provideRouter } from '@angular/router';
import { ProjectChatComponent } from './project-chat';
import { EMPTY_PROJECT_PROFILE, ProjectPropertyType, ProjectSalesAsset, ProjectSource } from './project-onboarding.models';

const galleryMime = 'application/vnd.blackpenguin.property-gallery+html';
const type = () => ({id:'type-1',project_id:'project-1',name:'Residence',description:'Unsaved details',features:[],media:[{source_id:'photo-1',id:'media-1'}],images_status:'provided',review_status:'confirmed',updated_at:'2026-11-09T00:00:00Z'} as unknown as ProjectPropertyType);
const document = () => ({id:'doc-1',property_type_id:'type-1',mime_type:'application/pdf',display_name:'Floor plans',content_tags:['floor_plan'],allowed_channels:['sms','whatsapp'],approval_status:'archived',source_id:'pdf-source',extracted_links:[],version:1} as unknown as ProjectSalesAsset);

describe('Project property editor and reviewed resource controls', () => {
  let component: ProjectChatComponent;
  let fixture: ComponentFixture<ProjectChatComponent>;
  let http: HttpTestingController;
  beforeEach(async () => {
    vi.spyOn(ProjectChatComponent.prototype,'ngOnInit').mockImplementation(() => undefined);
    await TestBed.configureTestingModule({imports:[ProjectChatComponent],providers:[provideHttpClient(),provideHttpClientTesting(),provideRouter([]),{provide:ActivatedRoute,useValue:{snapshot:{paramMap:{get:()=> 'project-1'},queryParamMap:{get:()=>null}}}}]}).compileComponents();
    fixture = TestBed.createComponent(ProjectChatComponent);
    component = fixture.componentInstance;
    component.projectId = 'project-1';
    vi.spyOn(component as any,'syncState').mockImplementation(() => undefined);
    http = TestBed.inject(HttpTestingController);
  });
  afterEach(() => { http.verify(); TestBed.resetTestingModule(); });

  it('opens an approved material directly without downloading its private source', () => {
    const open = vi.spyOn(window, 'open').mockImplementation(() => null);
    component.previewSalesAsset({...document(),approval_status:'approved',resource_url:'https://example.com/public-pdf'});
    expect(open).toHaveBeenCalledWith('https://example.com/public-pdf','_blank','noopener,noreferrer');
    http.expectNone(request => request.url.includes('/file'));
    open.mockRestore();
  });

  it('opens the catalog through the atomic editor transition and retains previous question history', () => {
    const load = vi.spyOn(component,'loadPropertyTypes').mockImplementation(() => undefined);
    vi.spyOn(component as any,'loadSalesAssets').mockImplementation(() => undefined);
    const question = {field:'target_audience',input_type:'text'} as never;
    component.nextQuestion=question;component.openEditorTask('catalog');
    const request=http.expectOne(request=>request.url.endsWith('/editor/catalog'));
    expect(request.request.body.transition.expected_navigation_revision).toBe(0);
    const next={field:'property_type_catalog',input_type:'property_type_catalog',task:'catalog'};
    request.flush({message:{id:'catalog-q',sender:'ai',created_at:'2026-11-09',content:'Catalog',ui_payload:next},profile:EMPTY_PROJECT_PROFILE,sources:[],next_question:next});
    expect(component.catalogEditorOpen).toBe(true);expect(component.activeEditorTask).toBe('catalog');
    expect(load).toHaveBeenCalledOnce();expect(question).toEqual({field:'target_audience',input_type:'text'});
  });

  it('lets the user choose a saved property without mutating other types', () => {
    component.propertyCatalog = {...component.propertyCatalog,items:[type(),{...type(),id:'type-2',name:'Apartment'}]};
    component.selectedPropertyId = 'type-2';
    expect(component.visiblePropertyTypes.map(item => item.name)).toEqual(['Apartment']);
    expect(component.propertyCatalog.items.length).toBe(2);
  });

  it('edits a confirmed extraction with its expected revision and preserves cancel', () => {
    const source = {id:'source-1',proposals:[{id:'proposal-1',field:'project_name',label:'Project name',status:'confirmed',value:'Original',draftValue:'Original',revision:2}]} as ProjectSource;
    component.sources = [source];
    component.editProposalRevision(source,source.proposals[0]);
    let proposal = component.sources[0].proposals[0];
    expect(proposal.editing).toBe(true);
    component.onProposalDraftChange(source,proposal,'New name');
    proposal = component.sources[0].proposals[0];
    component.saveProposalRevision(source,proposal);
    const request = http.expectOne(request => request.url.endsWith('/proposals/proposal-1/revision'));
    expect(request.request.body).toEqual({value:'New name',expected_revision:2});
    request.flush({proposal:{...proposal,status:'corrected',value:'New name',revision:3},profile:EMPTY_PROJECT_PROFILE});
    expect(component.sources[0].proposals[0].editing).toBe(false);
    component.editProposalRevision(component.sources[0],component.sources[0].proposals[0]);
    component.onProposalDraftChange(component.sources[0],component.sources[0].proposals[0],'Discarded edit');
    component.cancelProposalRevision(component.sources[0],component.sources[0].proposals[0]);
    expect(component.sources[0].proposals[0].draftValue).toBe('New name');
  });

  it('keeps the editing draft if another administrator revised the source', () => {
    const source = {id:'source-1',proposals:[{id:'p',field:'project_name',status:'confirmed',value:'Original',draftValue:'My unsaved name',revision:1,editing:true}]} as ProjectSource;
    component.sources = [source];
    component.saveProposalRevision(source,source.proposals[0]);
    http.expectOne(request => request.url.endsWith('/proposals/p/revision')).flush({detail:'This value was revised elsewhere. Reload it before saving.'},{status:409,statusText:'Conflict'});
    expect(component.sources[0].proposals[0].draftValue).toBe('My unsaved name');
    expect(component.sources[0].proposals[0].editing).toBe(true);
    expect(component.sources[0].proposals[0].inlineError).toContain('revised elsewhere');
  });

  it('preserves confirmed-field drafts and their original revision during polling', () => {
    const source = {id:'s',proposals:[{id:'p',field:'project_name',status:'confirmed',value:'Saved',draftValue:'My draft',revision:2,editing:true}]} as ProjectSource;
    component.sources = [source];
    const prepared = (component as any).prepareSources([{...source,proposals:[{...source.proposals[0],draftValue:undefined,editing:undefined}]}]);
    expect(prepared[0].proposals[0]).toMatchObject({editing:true,draftValue:'My draft',revision:2});
  });

  it('removes a photo without replacing unsaved scalar fields', () => {
    const item = type(); component.propertyCatalog = {...component.propertyCatalog,items:[item]};
    component.dirtyPropertyTypeIds.add(item.id);
    vi.spyOn(component as any,'syncState').mockImplementation(() => undefined);
    vi.spyOn(component as any,'loadSalesAssets').mockImplementation(() => undefined);
    component.removePropertyImage(item,'photo-1');
    http.expectOne(request => request.url.endsWith('/property-types/type-1/media/photo-1')).flush({...item,media:[],description:'Old server details',images_status:'pending'});
    expect(component.propertyCatalog.items[0].description).toBe('Unsaved details');
    expect(component.propertyCatalog.items[0].media).toEqual([]);
    expect(component.dirtyPropertyTypeIds.has(item.id)).toBe(true);
  });

  it('publishes only the attached image selection and refreshes the same gallery resource', () => {
    const item = type(); component.propertyGalleryAccess[item.id] = true;
    component.savePropertyGallery(item);
    const request = http.expectOne(request => request.url.endsWith('/property-types/type-1/gallery'));
    expect(request.request.body).toEqual({accessible_to_leads:true,source_ids:['photo-1']});
    request.flush({...document(),id:'gallery-1',mime_type:galleryMime,approval_status:'approved',resource_url:'https://example.com/gallery-v2'});
    expect(component.propertyGallery(item)?.resource_url).toBe('https://example.com/gallery-v2');
    expect(component.propertyDocuments(item)).toEqual([]);
  });

  it('sends PDF contents and lead access as explicit upload choices', () => {
    const item = type(); component.propertyDocumentAccess[item.id] = true;
    component.propertyDocumentTags[item.id] = ['floor_plan','gallery_image'];
    const file = new File(['test PDF bytes'],'plans.pdf',{type:'application/pdf'});
    component.uploadPropertyDocument(item,{target:{files:[file],value:'plans.pdf'}} as unknown as Event);
    const request = http.expectOne(request => request.url.endsWith('/property-types/type-1/documents'));
    const body = request.request.body as FormData;
    expect(body.get('accessible_to_leads')).toBe('true');
    expect(body.get('content_tags')).toBe('["floor_plan","gallery_image"]');
    request.flush(document());
    expect(component.propertyDocuments(item).length).toBe(1);
  });

  it('removes the PDF association after explicit confirmation', () => {
    const item = type(), asset = document(); component.salesAssets = [asset];
    vi.spyOn(window,'confirm').mockReturnValue(true);
    component.removePropertyDocument(item,asset);
    const request = http.expectOne(request => request.url.endsWith('/property-types/type-1/documents/doc-1'));
    expect(request.request.method).toBe('DELETE'); request.flush(null);
    expect(component.propertyDocuments(item)).toEqual([]);
  });
  it('renders Edit for confirmed source fields and enables the input on click', async () => {
    component.initialState = 'ready'; component.showWelcome = false;
    component.sources = [{id:'source-1',kind:'url',status:'ready',name:'Website',url:'https://example.com',proposals:[{id:'p',field:'project_name',label:'Project name',status:'confirmed',value:'Original project',draftValue:'Original project',revision:1}]} as ProjectSource];
    fixture.detectChanges();
    await fixture.whenStable(); fixture.detectChanges();
    const card = fixture.nativeElement.querySelector('[data-proposal-id="p"]') as HTMLElement;
    expect(card).toBeTruthy();
    expect(card.querySelector('textarea')!.disabled).toBe(true);
    const edit = [...card.querySelectorAll('button')].find(button => button.textContent?.trim() === 'Edit');
    expect(edit).toBeTruthy(); edit!.click(); fixture.detectChanges(); await fixture.whenStable(); fixture.detectChanges();
    expect(card.querySelector('textarea')!.disabled).toBe(false);
    expect(card.textContent).toContain('Cancel');
  });

  it('renders property PDF and gallery permissions inside the saved type card', () => {
    component.initialState = 'ready'; component.showWelcome = false; component.catalogEditorOpen = true;
    component.propertyCatalog = {...component.propertyCatalog,items:[type()],confirmed_count:1};
    component.salesAssets = [document()]; fixture.detectChanges();
    const resources = fixture.nativeElement.querySelector('[data-testid="property-resources"]') as HTMLElement;
    expect(resources).toBeTruthy();
    expect(resources.textContent).toContain('Gallery accessible to leads');
    expect(resources.textContent).toContain('Floor plans');
    expect(resources.textContent).toContain('Internal only');
    expect(resources.querySelector('input[accept="application/pdf"]')).toBeTruthy();
    expect(resources.textContent).toContain('Remove image');
    expect(resources.textContent).toContain('Remove PDF');
  });

  it('previews a newly uploaded internal PDF before source history is reloaded', () => {
    const asset = {...document(),source_download_url:'/api/v1/projects/project-1/sources/pdf-source/file'};
    component.sources = [];
    component.previewSalesAsset(asset);
    const request = http.expectOne(request => request.url.endsWith('/sources/pdf-source/file'));
    expect(request.request.method).toBe('GET');
    request.flush(new Blob(['Unavailable']),{status:404,statusText:'Not found'});
    expect(component.errorMessage).toBe('The material could not be previewed.');
  });

  it('does not render a generated gallery as an extraction proposal', () => {
    const generated = {id:'gallery-source',kind:'uploaded_file',mime_type:galleryMime,status:'ready',proposals:[]} as unknown as ProjectSource;
    expect(component.isReviewableSource(generated)).toBe(false);
  });

});
