import { CommonModule } from '@angular/common';
import { Component, EventEmitter, Input, Output, isDevMode } from '@angular/core';
import { HttpClient } from '@angular/common/http';

export type DeferredCards = Record<string, {deferred: boolean; resumed?: boolean; draft: Record<string, any>; updated_at?: string}>;

@Component({selector:'app-configure-later', standalone:true, imports:[CommonModule], template:`
  <div class="my-3 rounded-lg border border-amber-400/25 bg-amber-400/5 p-3 text-xs">
    <p *ngIf="records[card]?.deferred" class="mb-2 text-amber-200">Saved for later: {{label}}. This grants no new approval. Required reviews still block final approval; operational setup still blocks its own capability.</p>
    <button type="button" (click)="save()" [disabled]="busy || !entityId" class="rounded border border-amber-300/40 px-3 py-2 text-amber-200 disabled:opacity-50">{{busy ? 'Saving…' : (records[card]?.deferred ? 'Resume configuration' : 'Configure later')}}</button>
    <p *ngIf="error" role="alert" class="mt-2 text-red-300">{{error}}</p>
  </div>`})
export class ConfigureLaterComponent {
  @Input() scope: 'company'|'project' = 'project';
  @Input() entityId=''; @Input() card=''; @Input() label='This configuration';
  @Input() draft: Record<string, any> = {}; @Input() records: DeferredCards = {};
  @Output() saved = new EventEmitter<DeferredCards>();
  busy=false; error='';
  constructor(private http:HttpClient) {}
  save() {
    if (this.busy || !this.entityId) return;
    this.busy=true;this.error='';
    const base=(isDevMode() ? 'http://localhost:8000' : '')+'/api/v1/onboarding-deferrals';
    this.http.post<{deferrals:DeferredCards}>(`${base}/${this.scope}/${encodeURIComponent(this.entityId)}`,{card:this.card,resume:!!this.records[this.card]?.deferred,draft:this.draft}).subscribe({next:r=>{this.records=r.deferrals;this.busy=false;this.saved.emit(r.deferrals);},error:e=>{this.busy=false;this.error=typeof e.error?.detail==='string' ? e.error.detail : 'Your configuration could not be saved. Nothing was approved. Please retry.';}});
  }
}

export function restoreDraft(target: Record<string, any>, saved?: Record<string, any>) {
  if (!saved) return;
  for (const key of Object.keys(target)) if (Object.prototype.hasOwnProperty.call(saved,key) && !['__proto__','constructor','prototype','id','project_id','review_status','approval_status','version','created_at','updated_at','approved_at','approved_by_user_id'].includes(key)) target[key]=saved[key];
}
