import { CommonModule } from '@angular/common';
import { ChangeDetectorRef, Component, OnDestroy, OnInit } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { Subscription } from 'rxjs';
import { API_V1_URL } from '../../../core/config/api.config';
import { EngineStatus, SalesEngineControlComponent } from '../sales-engine-control/sales-engine-control';

type HermesConfiguration = {
  engine: string; provider: string; language: 'en'; model: string;
  allowed_models: string[]; system_prompt: string; max_iterations: number;
  enabled_tools: string[]; enabled: boolean;
};
type Version = {id: string; version: number; change_note: string; created_at: string; published_at?: string | null; is_published: boolean};

@Component({
  selector: 'app-hermes-sales-settings',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink, SalesEngineControlComponent],
  template: `
    <main class="bp-page">
      <div class="bp-page__container bp-page__container--form space-y-6">
        <header class="border-b border-white/10 pb-5">
          <a routerLink="/admin/ai-settings" class="text-sm text-secondary underline">AI Settings</a>
          <h1 class="mt-2 text-3xl font-light">Hermes <span class="text-secondary font-semibold">Sales Core</span></h1>
          <p class="mt-2 text-sm text-gray-400">One global configuration for every Company and Project · Staff Superadmin only · English only</p>
        </header>
        <app-sales-engine-control editor="hermes" [refreshKey]="routingRefreshKey" [locked]="busy || loading"
          (writingChange)="routingBusy=$event" (selectionChanged)="onSelectionChanged($event)"></app-sales-engine-control>
        <section class="rounded-xl border border-white/10 bg-white/5 p-4 text-sm">
          <strong>Independent Hermes policy editor.</strong> Drafts, publication and restoration do not select an engine. The protected backend readiness gate controls live activation. Editing Hermes never changes LangGraph stages, segments or prompts.
        </section>
        <p *ngIf="error" role="alert" class="rounded border border-red-700 p-3 text-red-300">{{ error }}</p>
        <p *ngIf="notice" role="status" class="rounded border border-gray-600 p-3">{{ notice }}</p>
        <p *ngIf="loading">Loading global configuration…</p>
        <button *ngIf="!loading && !config" type="button" [disabled]="locked" (click)="load()" class="rounded border border-white/20 px-4 py-2">Reload policy</button>
        <ng-container *ngIf="!loading && config as cfg">
          <section class="rounded-xl border border-white/10 bg-white/5 p-5 space-y-4">
            <header class="flex flex-wrap items-center justify-between gap-3">
              <div><h2 class="text-lg font-semibold">Hermes policy editor</h2><p class="text-xs text-gray-400">{{editorSource}} · Local edits are not published until explicitly saved and published.</p></div>
              <span class="text-xs text-gray-400">{{publishedVersionId ? 'A global policy is published' : 'Built-in baseline (not published)'}}</span>
            </header>
            <fieldset [disabled]="locked" class="space-y-4 min-w-0">
              <div class="grid gap-4 sm:grid-cols-2">
                <label class="text-xs text-gray-400">Provider<input [value]="cfg.provider" disabled class="mt-1 w-full rounded bg-black/50 p-3 text-white" /></label>
                <label class="text-xs text-gray-400">Language<input [value]="'English (en) — only available language'" disabled class="mt-1 w-full rounded bg-black/50 p-3 text-white" /></label>
                <label class="text-xs text-gray-400">Selected model
                  <select [(ngModel)]="cfg.model" class="mt-1 w-full rounded border border-white/20 bg-black p-3 text-white">
                    <option *ngFor="let model of cfg.allowed_models" [ngValue]="model">{{model}}</option>
                  </select>
                </label>
                <label class="text-xs text-gray-400">Maximum Hermes tool iterations (1–12)
                  <input type="number" min="1" max="12" step="1" [(ngModel)]="cfg.max_iterations" class="mt-1 w-full rounded border border-white/20 bg-black p-3 text-white" />
                </label>
              </div>
              <label class="block text-xs text-gray-400">Allowed OpenRouter model identifiers (one per line)
                <textarea rows="3" [ngModel]="modelsText" (ngModelChange)="changeModels($event)" class="mt-1 w-full rounded border border-white/20 bg-black p-3 font-mono text-sm text-white"></textarea>
              </label>
              <p *ngIf="!cfg.allowed_models.includes(cfg.model)" class="text-xs text-amber-300">Choose a model from the allowed list before saving.</p>
              <label class="block text-xs text-gray-400">Global system prompt
                <textarea rows="16" [(ngModel)]="cfg.system_prompt" maxlength="50000" class="mt-1 w-full rounded border border-white/20 bg-black p-3 font-mono text-sm leading-relaxed text-white"></textarea>
              </label>
              <div>
                <h3 class="text-sm font-medium">Permitted business tools</h3>
                <p class="mb-3 text-xs text-gray-400">Authorization, tenant isolation, consent, bookings and materials approvals remain enforced in backend code.</p>
                <div class="grid gap-2 sm:grid-cols-2">
                  <label *ngFor="let tool of availableTools" class="flex items-center gap-2 text-xs"><input type="checkbox" [checked]="hasTool(tool)" (change)="toggleTool(tool, $any($event.target).checked)" />{{ tool }}</label>
                </div>
              </div>
              <label class="flex items-center gap-2 text-sm">
                <input type="checkbox" [(ngModel)]="cfg.enabled" /> Permit this policy to be used at a controlled Hermes cutover (not an engine selection)
              </label>
              <label class="block text-xs text-gray-400">Change note (required for saving and publishing together)
                <input [(ngModel)]="changeNote" maxlength="500" placeholder="Reason for this version" class="mt-1 w-full rounded border border-white/20 bg-black p-3 text-white" />
              </label>
              <div class="flex flex-wrap gap-3">
                <button type="button" [disabled]="locked || !validConfig" (click)="save(false)" class="rounded border border-white/30 px-4 py-2 disabled:opacity-50">Save draft</button>
                <button type="button" [disabled]="locked || !validConfig || !changeNote.trim()" (click)="save(true)" class="rounded bg-secondary px-4 py-2 font-semibold text-black disabled:opacity-50">Save and publish</button>
                <button type="button" [disabled]="locked" (click)="load()" class="rounded border border-white/10 px-4 py-2">Reload published policy</button>
              </div>
            </fieldset>
          </section>
          <section class="rounded-xl border border-white/10 bg-white/5 p-5">
            <h2 class="mb-3 text-lg font-semibold">Global version history</h2>
            <p class="mb-3 text-xs text-gray-400">Restoration creates a new published version. Past records remain auditable. Routing changes are recorded here and do not modify the saved policy fields.</p>
            <p *ngIf="historyError" role="alert" class="text-xs text-red-300">{{historyError}}</p>
            <p *ngIf="!versions.length && !historyError" class="text-sm text-gray-400">No versions created yet.</p>
            <div *ngFor="let v of versions" class="flex flex-wrap items-center justify-between gap-3 border-t border-white/10 py-3">
              <div><strong>Version {{v.version}}</strong> <span class="text-xs text-gray-400">· {{v.is_published ? 'Published' : v.published_at ? 'Historical publication' : 'Draft'}} · {{v.created_at | date:'medium'}}</span><p class="text-xs text-gray-400">{{v.change_note || 'No change note'}}</p></div>
              <div class="flex gap-2">
                <button type="button" [disabled]="locked" (click)="loadVersion(v)" class="rounded border px-3 py-1 text-xs">Edit copy</button>
                <button type="button" *ngIf="!v.is_published && !v.published_at" [disabled]="locked" (click)="publish(v.id)" class="rounded bg-secondary px-3 py-1 text-xs text-black">Publish</button>
                <button type="button" *ngIf="!v.is_published" [disabled]="locked" (click)="restore(v.id)" class="rounded border px-3 py-1 text-xs">Restore as new</button>
              </div>
            </div>
          </section>
        </ng-container>
      </div>
    </main>
  `
})
export class HermesSalesSettingsComponent implements OnInit, OnDestroy {
  config: HermesConfiguration | null = null;
  availableTools: string[] = [];
  versions: Version[] = [];
  publishedVersionId: string | null = null;
  loading = true; busy = false; error = ''; notice = ''; changeNote = ''; historyError = '';
  editorSource = 'Published policy'; routingRefreshKey = 0; routingBusy = false;
  private readonly url = `${API_V1_URL}/ai/hermes`;
  private readonly requests = new Subscription();
  private historyRequest?: Subscription;
  constructor(private http: HttpClient, private cdr: ChangeDetectorRef) {}
  ngOnInit(): void { this.load(); }
  ngOnDestroy(): void { this.requests.unsubscribe(); this.historyRequest?.unsubscribe(); }
  get locked(): boolean { return this.loading || this.busy || this.routingBusy; }
  get modelsText(): string { return (this.config?.allowed_models || []).join('\n'); }
  get validConfig(): boolean {
    const c = this.config;
    return !!c && c.allowed_models.length>0 && c.allowed_models.length<=30 && c.allowed_models.includes(c.model) &&
      new Set(c.allowed_models).size===c.allowed_models.length && c.allowed_models.every(m=>/^[A-Za-z0-9][A-Za-z0-9._+:/-]{2,119}$/.test(m)) &&
      Number.isInteger(c.max_iterations) && c.max_iterations>=1 && c.max_iterations<=12 &&
      c.system_prompt.length>=100 && c.system_prompt.length<=50000;
  }
  changeModels(value: string): void { if (this.config) this.config.allowed_models = value.split('\n').map(x=>x.trim()).filter(Boolean); }
  hasTool(tool: string): boolean { return !!this.config?.enabled_tools.includes(tool); }
  toggleTool(tool: string, checked: boolean): void {
    if (!this.config || this.locked || !this.availableTools.includes(tool)) return;
    this.config.enabled_tools = checked ? [...new Set([...this.config.enabled_tools,tool])] : this.config.enabled_tools.filter(x=>x!==tool);
  }
  private fail(err: any): void {
    const detail = err?.error?.detail;
    this.error = typeof detail==='string' ? detail : 'The requested policy operation failed. Check inputs and try again.';
    this.busy = false; this.loading = false; this.routingRefreshKey++; this.cdr.markForCheck();
  }
  // Engine selection creates an audit version with the same policy. Never discard
  // an unsaved policy editor because a separate routing operation completed.
  onSelectionChanged(status: EngineStatus): void {
    this.publishedVersionId = status.published_version_id;
    this.fetchVersions(); this.cdr.markForCheck();
  }
  load(): void {
    if (this.busy || this.routingBusy) return;
    this.loading = true; this.error = '';
    this.requests.add(this.http.get<any>(`${this.url}/global`).subscribe({next: data => {
      this.config = data.configuration;
      this.availableTools = data.available_tools || [];
      this.publishedVersionId = data.published_version_id || null;
      this.editorSource = this.publishedVersionId?'Copy of published policy':'Built-in baseline';
      this.changeNote = ''; this.loading = false; this.routingRefreshKey++;
      this.fetchVersions(); this.cdr.markForCheck();
    },error: err=>{this.config=null;this.fail(err);}}));
  }
  private fetchVersions(): void {
    this.historyRequest?.unsubscribe(); this.historyError = '';
    this.historyRequest = this.http.get<any>(`${this.url}/versions?page=1&page_size=50`).subscribe({next: data => {
      this.versions = data.items || []; this.cdr.markForCheck();
    },error:()=>{this.versions=[];this.historyError='Version history could not be loaded.';this.cdr.markForCheck();}});
  }
  save(publishNow: boolean): void {
    if (this.locked || !this.config || !this.validConfig || (publishNow && !this.changeNote.trim())) return;
    this.busy = true; this.error = ''; this.notice = '';
    this.requests.add(this.http.post<Version>(`${this.url}/drafts`,{configuration:this.config,change_note:this.changeNote}).subscribe({next: version=>{
      if (!publishNow) {
        this.busy=false;this.notice=`Draft ${version.version} saved. Routing unchanged.`;this.editorSource=`Copy of draft ${version.version}`;
        this.changeNote='';this.routingRefreshKey++;this.fetchVersions();this.cdr.markForCheck();return;
      }
      this.publishInternal(version.id);
    },error:err=>this.fail(err)}));
  }
  publish(id: string): void {
    if (this.locked) return;
    this.busy=true;this.error='';this.notice='';this.publishInternal(id);
  }
  private publishInternal(id: string): void {
    this.requests.add(this.http.post(`${this.url}/versions/${encodeURIComponent(id)}/publish`,{}).subscribe({next:()=>{
      this.busy=false;this.notice='Policy published globally. Engine selection unchanged.';this.load();
    },error:err=>this.fail(err)}));
  }
  restore(id: string): void {
    if (this.locked) return;
    this.busy=true;this.error='';this.notice='';
    this.requests.add(this.http.post(`${this.url}/versions/${encodeURIComponent(id)}/restore`,{}).subscribe({next:()=>{
      this.busy=false;this.notice='A new published policy version was created. Engine selection unchanged.';this.load();
    },error:err=>this.fail(err)}));
  }
  loadVersion(version: Version): void {
    if (this.locked) return;
    this.busy=true;this.error='';
    this.requests.add(this.http.get<any>(`${this.url}/versions/${encodeURIComponent(version.id)}`).subscribe({next:data=>{
      this.config=data.configuration;this.changeNote=`Based on version ${version.version}`;this.editorSource=`Copy of version ${version.version}`;
      this.busy=false;this.notice='Historical configuration loaded into editor, not published.';this.cdr.markForCheck();
    },error:err=>this.fail(err)}));
  }
}
