import { CommonModule } from '@angular/common';
import { Component, EventEmitter, Input, Output, isDevMode } from '@angular/core';
import { HttpClient } from '@angular/common/http';

export type DeferredCards = Record<string, {deferred: boolean; resumed?: boolean; draft: Record<string, any>; updated_at?: string}>;
export function questionCard(question:{field?:string|null;input_type?:string}):string {
  if(question.input_type==='documents') return 'documents';
  if(question.input_type==='meta_task_choice') return 'meta_setup';
  return question.field ? 'field:'+question.field : 'final_approval';
}

@Component({selector:'app-configure-later', standalone:true, imports:[CommonModule], template:`
  <div class="my-3 flex flex-wrap items-center gap-2 text-xs">
    <p *ngIf="records[card]?.deferred" class="mb-2 text-amber-200">Saved for later: {{label}}. This grants no new approval. Required reviews still block final approval; operational setup still blocks its own capability.</p>
    <p *ngIf="records[card]?.updated_at" class="mb-2">{{label}} · {{records[card].deferred ? 'Pending' : (records[card].resumed ? 'Review resumed' : 'Review saved')}} · {{records[card].updated_at | date:'medium'}}</p>
    <details *ngIf="records[card]?.draft && draftSummary" class="mb-2"><summary>Saved draft (not approved)</summary><pre class="whitespace-pre-wrap break-words">{{draftSummary}}</pre></details>
    <button type="button" (click)="save()" [disabled]="busy || blocked || !entityId" class="rounded border border-amber-300/40 px-3 py-2 text-amber-200 disabled:opacity-50">{{busy ? 'Saving…' : (records[card]?.deferred ? 'Resume configuration' : (card === 'final_approval' ? 'Continue review later' : 'Complete later'))}}</button>
    <a *ngIf="records[card]?.deferred && !busy" [href]="scope === 'project' ? '/app/projects' : '/app/dashboard'" class="ml-3 underline">Draft saved · Exit onboarding</a>
    <p *ngIf="error" role="alert" class="mt-2 text-red-300">{{error}}</p>
  </div>`})
export class ConfigureLaterComponent {
  @Input() scope: 'company'|'project' = 'project';
  @Input() entityId=''; @Input() card=''; @Input() label='This configuration';
  @Input() draft: Record<string, any> = {}; @Input() records: DeferredCards = {};
  @Input() blocked=false;
  @Output() saved = new EventEmitter<DeferredCards>();
  busy=false; error='';
  constructor(private http:HttpClient) {}
  get draftSummary():string { return formatDraftSummary(this.records[this.card]?.draft); }
  save() {
    if (this.busy || this.blocked || !this.entityId) return;
    this.busy=true;this.error='';
    const base=(isDevMode() ? 'http://localhost:8000' : '')+'/api/v1/onboarding-deferrals';
    this.http.post<{deferrals:DeferredCards}>(`${base}/${this.scope}/${encodeURIComponent(this.entityId)}`,{card:this.card,resume:!!this.records[this.card]?.deferred,draft:this.draft}).subscribe({next:r=>{this.records=r.deferrals;this.busy=false;this.saved.emit(r.deferrals);},error:e=>{this.busy=false;this.error=typeof e.error?.detail==='string' ? e.error.detail : 'Your configuration could not be saved. Nothing was approved. Please retry.';}});
  }
}

export function restoreDraft(target: Record<string, any>, saved?: Record<string, any>) {
  if (!saved) return;
  for (const key of Object.keys(target)) if (Object.prototype.hasOwnProperty.call(saved,key) && !['__proto__','constructor','prototype','id','project_id','review_status','approval_status','version','created_at','updated_at','approved_at','approved_by_user_id'].includes(key)) target[key]=saved[key];
}

export function formatDraftSummary(draft?:Record<string,any>):string {
  if(!draft) return '';
  return Object.entries(draft).filter(([key])=>!['details_base','id','project_id','created_at','updated_at'].includes(key)).map(([key,value])=>{
    const label=key.replace(/_/g,' ').replace(/([a-z])([A-Z])/g,'$1 $2');
    if(key==='selected_images') return `Selected images: ${Array.isArray(value) ? value.length : 0}`;
    const text=Array.isArray(value) ? value.map(item=>typeof item==='object' && item!==null ? formatDraftSummary(item) : String(item)).join('\n')
      : value!==null && typeof value==='object' ? formatDraftSummary(value) : String(value ?? 'Not specified');
    return `${label}: ${text}`;
  }).join('\n');
}
