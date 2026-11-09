import { ChangeDetectorRef, Component, EventEmitter, Input, OnInit, Output, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ProjectOnboardingService } from './project-onboarding.service';
import { ProjectSalesAsset, MaterialCoverage, MaterialTarget, SalesAssetType } from './project-onboarding.models';

export function coveragePages(text: string): number[] {
  if (!text.trim()) return [];
  const pages: number[] = [];
  for (const part of text.split(',')) {
    const match = part.trim().match(/^(\d+)(?:\s*-\s*(\d+))?$/);
    if (!match) throw new Error('Use page numbers such as 1, 3-5.');
    const start = Number(match[1]), end = Number(match[2] || match[1]);
    if (start < 1 || end < start || end > 5000 || end-start > 99) throw new Error('Use valid page ranges (up to 100 pages).');
    for (let p=start; p<=end; p++) pages.push(p);
    if (pages.length > 100) throw new Error('Use up to 100 pages per target.');
  }
  return [...new Set(pages)].sort((a,b)=>a-b);
}

@Component({selector:'app-material-coverage-editor', standalone:true, imports:[CommonModule,FormsModule],
 template:`<section class="mt-4 rounded-xl border border-amber-400/30 p-4" aria-label="Material coverage editor">
 <h3 class="text-sm font-semibold">Review material coverage · {{asset.display_name}}</h3>
 <p class="mt-2 text-xs text-gray-400">Select every property or unit covered by this file and confirm its contents. Page numbers are references; the shared link opens the whole file. Saving revokes previous links and requires approval again.</p>
 <p *ngIf="error" role="alert" class="mt-2 text-sm text-red-300">{{error}}</p>
 <fieldset *ngFor="let row of rows; let i=index" class="mt-3 rounded-lg border border-white/10 p-3" [disabled]="busy">
 <legend class="text-xs">Coverage {{i+1}}</legend>
 <label class="block text-xs">Property / unit<select class="mt-1 block w-full bg-black p-2" [(ngModel)]="row.target"><option *ngFor="let target of targets" [value]="target.key">{{target.label}}</option></select></label>
 <div class="mt-2 flex flex-wrap gap-3"><label *ngFor="let tag of tags" class="text-xs"><input type="checkbox" [checked]="row.tags.includes(tag)" (change)="toggle(row,tag)"> {{tag === 'gallery_image' ? 'Photos / images' : tag.replaceAll('_',' ')}}</label></div>
 <label *ngIf="asset.mime_type==='application/pdf'" class="mt-2 block text-xs">PDF pages (optional)<input class="mt-1 block w-full bg-black p-2" [(ngModel)]="row.pages" placeholder="1, 3-5"></label>
 <label class="mt-2 block text-xs">What this material covers (optional)<input class="mt-1 block w-full bg-black p-2" [(ngModel)]="row.summary" maxlength="500"></label>
 <button type="button" class="mt-2 text-xs text-red-300" (click)="rows.splice(i,1)">Remove target</button>
 </fieldset>
 <div class="mt-3 flex flex-wrap gap-3 text-xs"><button type="button" [disabled]="busy || !targets.length" (click)="add()">Add property / unit</button><button type="button" [disabled]="busy || !targets.length || !rows.length" (click)="save()">Save coverage for review</button><button type="button" [disabled]="busy" (click)="closed.emit()">Cancel</button></div>
 </section>`})
export class MaterialCoverageEditor implements OnInit {
 @Input({required:true}) projectId=''; @Input({required:true}) asset!:ProjectSalesAsset;
 @Output() saved=new EventEmitter<ProjectSalesAsset>(); @Output() closed=new EventEmitter<void>();
 readonly service=inject(ProjectOnboardingService); readonly cdr=inject(ChangeDetectorRef);
 readonly tags:SalesAssetType[]=['brochure','gallery_image','floor_plan','unit_sheet','price_list','amenities','location_map','virtual_tour','legal_disclaimer','other'];
 targets:MaterialTarget[]=[]; rows:Array<{target:string; tags:SalesAssetType[]; pages:string; summary:string}>=[];
 busy=false; error='';
 ngOnInit():void {
  const coverage=this.asset.coverage ?? [{property_type_id:this.asset.property_type_id,unit_id:null,content_tags:this.asset.content_tags,pages:[],summary:''}];
  this.rows=coverage.map(c=>({target:c.unit_id?'unit:'+c.unit_id:c.property_type_id?'property:'+c.property_type_id:'project',tags:[...c.content_tags],pages:c.pages.join(', '),summary:c.summary}));
  this.service.getMaterialTargets(this.projectId).subscribe({next:items=>{this.targets=items;this.cdr.markForCheck();},error:()=>{this.error='Material targets could not be loaded. Please try again.';this.cdr.markForCheck();}});
 }
 add():void { this.rows.push({target:'',tags:[...this.asset.content_tags],pages:'',summary:''}); }
 toggle(row:{tags:SalesAssetType[]},tag:SalesAssetType):void {row.tags=row.tags.includes(tag)?row.tags.filter(t=>t!==tag):[...row.tags,tag];}
 save():void {
  if(this.busy)return;
  this.error='';let coverage:MaterialCoverage[];
  try {
   if(!this.rows.length)throw new Error('Select at least one target.');
   const seen=new Map<string,Set<SalesAssetType>>();
   for(const row of this.rows){const tags=seen.get(row.target)||new Set<SalesAssetType>();if(row.tags.some(t=>tags.has(t)))throw new Error('Combine repeated content for a target in one entry.');row.tags.forEach(t=>tags.add(t));seen.set(row.target,tags);}
   if(this.rows.some(r=>r.target==='project') && this.rows.some(r=>r.target!=='project'))throw new Error('Choose either the entire Project or named targets.');
   coverage=this.rows.map(row=>{
    const target=this.targets.find(t=>t.key===row.target);if(!target || !row.tags.length)throw new Error('Select a target and at least one content type.');
    return {property_type_id:target.property_type_id,unit_id:target.unit_id,content_tags:row.tags,pages:coveragePages(row.pages),summary:row.summary.trim()};
   });
  }catch(error){this.error=error instanceof Error?error.message:'Check the coverage entries.';return;}
  this.busy=true;
  const contentTags=[...new Set(coverage.flatMap(c=>c.content_tags))];
  this.service.updateSalesAsset(this.projectId,this.asset.id,{property_type_id:this.asset.property_type_id,asset_type:contentTags.includes(this.asset.asset_type)?this.asset.asset_type:contentTags[0],content_tags:contentTags,display_name:this.asset.display_name,description:this.asset.description,valid_from:this.asset.valid_from,valid_until:this.asset.valid_until,allowed_channels:this.asset.allowed_channels,coverage}).subscribe({
   next:asset=>{this.busy=false;this.saved.emit(asset);},error:response=>{this.busy=false;this.error=typeof response.error?.detail==='string'?response.error.detail:'The saved coverage could not be confirmed. Reload the material to check its current review before trying again.';this.cdr.markForCheck();}
  });
 }
}
