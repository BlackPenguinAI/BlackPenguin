import { TestBed,ComponentFixture } from '@angular/core/testing';
import { HttpTestingController,provideHttpClientTesting } from '@angular/common/http/testing';
import { provideHttpClient } from '@angular/common/http';
import { MaterialCoverageEditor,coveragePages } from './material-coverage-editor';
import { ProjectSalesAsset } from './project-onboarding.models';
import { ProjectChatComponent } from './project-chat';

const asset=()=>({id:'a',property_type_id:'p',source_id:'s',asset_type:'brochure',content_tags:['brochure'],display_name:'Reviewed PDF',description:null,mime_type:'application/pdf',allowed_channels:['sms','whatsapp'],valid_from:null,valid_until:null,approval_status:'approved',version:1} as ProjectSalesAsset);
const targets=[{key:'project',label:'Entire Project',property_type_id:null,unit_id:null},{key:'property:p',label:'Studio',property_type_id:'p',unit_id:null},{key:'unit:u',label:'Unit A101',property_type_id:null,unit_id:'u'}];

describe('Reviewed material coverage editor',()=>{
 let fixture:ComponentFixture<MaterialCoverageEditor>,c:MaterialCoverageEditor,http:HttpTestingController;
 beforeEach(async()=>{
  await TestBed.configureTestingModule({imports:[MaterialCoverageEditor],providers:[provideHttpClient(),provideHttpClientTesting()]}).compileComponents();
  fixture=TestBed.createComponent(MaterialCoverageEditor);c=fixture.componentInstance;http=TestBed.inject(HttpTestingController);
  fixture.componentRef.setInput('projectId','project');fixture.componentRef.setInput('asset',asset());fixture.detectChanges();
  http.expectOne(r=>r.url.endsWith('/project/material-targets')).flush(targets);fixture.detectChanges();
 });
 afterEach(()=>{http.verify();TestBed.resetTestingModule();});
 it('loads scoped targets and retains legacy association until explicitly saved',()=>{
  expect(c.rows[0].target).toBe('property:p');
  expect(fixture.nativeElement.textContent).toContain('opens the whole file');
  http.expectNone(r=>r.method==='PUT');
 });
 it('saves multiple targets with reviewed contents and page references',()=>{
  const saved=vi.spyOn(c.saved,'emit');c.rows=[{target:'property:p',tags:['gallery_image'],pages:'1, 3-4',summary:'Photos'},{target:'unit:u',tags:['floor_plan'],pages:'2',summary:'Plan'}];c.save();
  const request=http.expectOne(r=>r.url.endsWith('/project/sales-assets/a'));
  expect(request.request.method).toBe('PUT');expect(request.request.body.coverage[0].pages).toEqual([1,3,4]);
  expect(request.request.body.coverage[1].unit_id).toBe('u');expect(request.request.body.content_tags).toEqual(['gallery_image','floor_plan']);
  request.flush({...asset(),approval_status:'draft',version:2});expect(saved).toHaveBeenCalledWith(expect.objectContaining({approval_status:'draft',version:2}));
 });
 it('supports disjoint contents on different pages for the same target',()=>{
  c.rows=[{target:'property:p',tags:['gallery_image'],pages:'1',summary:'Photos'},{target:'property:p',tags:['floor_plan'],pages:'2',summary:'Plan'}];c.save();
  const request=http.expectOne(r=>r.method==='PUT');expect(request.request.body.coverage).toHaveLength(2);request.flush({...asset(),approval_status:'draft'});
 });
 it('blocks duplicate content and invalid ranges without sending an update',()=>{
  c.rows.push({...c.rows[0]});c.save();expect(c.error).toContain('repeated content');http.expectNone(r=>r.method==='PUT');
  c.rows.splice(1,1);c.rows[0].pages='0';c.save();expect(c.error).toContain('valid page');http.expectNone(r=>r.method==='PUT');
 });
 it('does not mix project-wide and named-target coverage',()=>{
  c.rows.push({target:'project',tags:['floor_plan'],pages:'',summary:''});c.save();expect(c.error).toContain('either');http.expectNone(r=>r.method==='PUT');
 });
 it('keeps the form available after a server scope rejection',()=>{
  const saved=vi.spyOn(c.saved,'emit');c.save();http.expectOne(r=>r.method==='PUT').flush({detail:'Target belongs to another Project'},{status:404,statusText:'Not Found'});
  expect(saved).not.toHaveBeenCalled();expect(c.busy).toBe(false);expect(c.error).toContain('another Project');
 });
 it('cancels without an update or approval request',()=>{
  const closed=vi.spyOn(c.closed,'emit');[...fixture.nativeElement.querySelectorAll('button')].find((b:any)=>b.textContent.trim()==='Cancel')!.click();expect(closed).toHaveBeenCalledOnce();http.expectNone(r=>r.method==='PUT'||r.method==='POST');
 });
});

describe('PDF page reference parsing',()=>{
 it.each(['0','5-2','1,','abc','1-5001','1-101'])('rejects invalid input %s',text=>expect(()=>coveragePages(text)).toThrow());
 it('returns distinct page numbers in order',()=>{expect(coveragePages('4, 2-3, 2')).toEqual([2,3,4]);expect(coveragePages('')).toEqual([]);});
});

describe('Owned and shared property galleries',()=>{
 it('keeps shared coverage separate from the gallery generation owner',()=>{
  const gallery={...asset(),mime_type:'application/vnd.blackpenguin.property-gallery+html',coverage:[{property_type_id:'other',unit_id:null,content_tags:['gallery_image'],pages:[],summary:''}]} as ProjectSalesAsset;
  const context={salesAssets:[gallery]};
  expect(ProjectChatComponent.prototype.propertyGallery.call(context as any,{id:'p'} as any)).toBe(gallery);
  expect(ProjectChatComponent.prototype.propertyGallery.call(context as any,{id:'other'} as any)).toBeUndefined();
  expect(ProjectChatComponent.prototype.sharedPropertyMaterials.call(context as any,{id:'other'} as any)).toEqual([gallery]);
  expect(ProjectChatComponent.prototype.sharedPropertyMaterials.call(context as any,{id:'p'} as any)).toEqual([]);
 });
});
