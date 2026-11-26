import { CommonModule } from '@angular/common';
import { HttpClient } from '@angular/common/http';
import { ChangeDetectorRef, Component, EventEmitter, Input, OnChanges, OnDestroy, OnInit, Output, SimpleChanges } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { Subscription } from 'rxjs';
import { API_V1_URL } from '../../../core/config/api.config';

export type SalesEngine = 'langgraph' | 'hermes';
export interface EngineStatus {
  active_sales_engine: SalesEngine | null;
  effective_sales_engine: SalesEngine | null;
  target_default_engine: SalesEngine;
  hermes_live_ready: boolean;
  available_engines: SalesEngine[];
  selectable_engines: SalesEngine[];
  automatic_fallback: boolean;
  error_code: string | null;
  published_version_id: string | null;
  published_policy_version: number | null;
  revision: number;
  hermes_policy_published: boolean;
  hermes_policy_valid: boolean;
  hermes_policy_enabled: boolean;
  hermes_policy_model: string | null;
}

@Component({
  selector: 'app-sales-engine-control',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink],
  template: `
    <section class="rounded-xl border border-white/10 bg-white/5 p-5 space-y-4" aria-label="Global sales engine routing">
      <header class="flex flex-wrap items-start justify-between gap-3">
        <div><p class="text-xs font-semibold uppercase tracking-widest text-secondary">Staff Superadmin · Global</p>
          <h2 class="mt-1 text-xl font-semibold">Sales engine control</h2>
          <p class="mt-1 text-xs text-gray-400">All Companies and Projects · Engine routing is independent of prompt publication.</p></div>
        <button type="button" (click)="load()" [disabled]="loading || writing" class="rounded border border-white/20 px-3 py-2 text-xs disabled:opacity-50">Refresh status</button>
      </header>
      <nav class="flex flex-wrap gap-2" aria-label="Sales engine configuration">
        <a routerLink="/admin/ai-settings" [attr.aria-current]="editor==='langgraph'?'page':null" class="rounded-lg border px-3 py-2 text-sm" [ngClass]="editor==='langgraph'?'border-secondary text-secondary':'border-white/20 text-gray-300'">LangGraph &amp; onboarding settings</a>
        <a routerLink="/admin/ai-settings/hermes" [attr.aria-current]="editor==='hermes'?'page':null" class="rounded-lg border px-3 py-2 text-sm" [ngClass]="editor==='hermes'?'border-secondary text-secondary':'border-white/20 text-gray-300'">Hermes settings</a>
      </nav>
      <p class="text-xs text-gray-400">Each editor remains available regardless of the selected engine. Save any draft before navigating away.</p>
      <p *ngIf="error" class="rounded border border-red-700 p-3 text-sm text-red-300" role="alert">{{error}}</p>
      <p *ngIf="notice" class="rounded border border-emerald-700 p-3 text-sm text-emerald-300" role="status">{{notice}}</p>
      <p *ngIf="loading" class="text-sm text-gray-400" role="status">Reading authoritative routing status…</p>
      <ng-container *ngIf="!loading && status as s">
        <div class="grid gap-3 sm:grid-cols-3">
          <article class="rounded-lg border border-white/10 bg-black/30 p-3"><p class="text-xs text-gray-400">Selected engine</p><strong>{{name(s.active_sales_engine)}}</strong></article>
          <article class="rounded-lg border border-white/10 bg-black/30 p-3"><p class="text-xs text-gray-400">Effective routing</p><strong>{{name(s.effective_sales_engine)}}</strong><p class="mt-1 text-xs text-gray-400">Routing state, not a provider health check.</p></article>
          <article class="rounded-lg border border-white/10 bg-black/30 p-3"><p class="text-xs text-gray-400">Target default</p><strong>{{name(s.target_default_engine)}}</strong><p class="mt-1 text-xs text-gray-400">Planned after certification, not automatically activated.</p></article>
        </div>
        <p *ngIf="s.error_code" class="rounded border border-amber-700 bg-amber-950/20 p-3 text-sm text-amber-100">Routing requires review: {{s.error_code}}. No automatic fallback is performed.</p>
        <div class="grid gap-3 md:grid-cols-2">
          <article class="rounded-lg border p-4 space-y-2" [ngClass]="s.active_sales_engine==='langgraph'?'border-secondary':'border-white/10'">
            <h3 class="font-semibold">LangGraph</h3>
            <p class="text-xs text-gray-400">Existing Sales workflow · Editable stages, segment strategies, scoring, cadence and prompt history.</p>
            <p class="text-xs">{{s.active_sales_engine==='langgraph'?'Selected':'Not selected'}} · {{canSelect('langgraph')?'Selectable':'Unavailable'}}</p>
            <button type="button" (click)="choose('langgraph')" [disabled]="locked || writing || !canSelect('langgraph') || s.active_sales_engine==='langgraph'" class="rounded border border-white/20 px-3 py-2 text-sm disabled:opacity-50">Select LangGraph</button>
          </article>
          <article class="rounded-lg border p-4 space-y-2" [ngClass]="s.active_sales_engine==='hermes'?'border-secondary':'border-white/10'">
            <h3 class="font-semibold">Hermes Agent</h3>
            <p class="text-xs text-gray-400">Nous Research SDK · Independent global system prompt, model and permitted tools.</p>
            <dl class="grid gap-1 text-xs">
              <div>Live readiness: <strong>{{s.hermes_live_ready?'Certified gate open':'Blocked — certification required'}}</strong></div>
              <div>Policy: {{!s.hermes_policy_published?'Not published':!s.hermes_policy_valid?'Requires review':s.hermes_policy_enabled?'Published and enabled':'Published but disabled'}}</div>
              <div *ngIf="s.published_policy_version!==null">Published version: {{s.published_policy_version}}</div>
              <div *ngIf="s.hermes_policy_model">Model: {{s.hermes_policy_model}}</div>
            </dl>
            <button type="button" (click)="choose('hermes')" [disabled]="locked || writing || !canSelect('hermes') || s.active_sales_engine==='hermes'" class="rounded border border-white/20 px-3 py-2 text-sm disabled:opacity-50">Select Hermes</button>
            <p *ngIf="!canSelect('hermes')" class="text-xs text-amber-300">{{blockReason(s)}}</p>
          </article>
        </div>
        <p class="text-xs text-gray-400">Automatic fallback: {{s.automatic_fallback?'Enabled — review required':'Disabled'}}. In-flight events retain their pinned engine; a selection applies to new eligible events only.</p>
        <section *ngIf="pending as target" class="rounded-lg border border-amber-700/60 bg-amber-950/10 p-4 space-y-3" aria-label="Confirm global engine selection">
          <h3 class="font-semibold">Change global routing to {{name(target)}}</h3>
          <p class="text-xs text-gray-400">This affects every Company and Project, not just this editor. Existing prompt configurations and conversation history remain preserved. The server rechecks the reviewed version and readiness.</p>
          <label class="block text-sm">Change note (required)
            <input [(ngModel)]="note" [ngModelOptions]="{standalone:true}" maxlength="400" [disabled]="writing || locked" class="mt-1 w-full rounded border border-white/20 bg-black p-2 text-white" placeholder="Why is this routing change needed?" />
          </label>
          <label class="flex items-start gap-2 text-sm"><input type="checkbox" [(ngModel)]="confirmed" [ngModelOptions]="{standalone:true}" [disabled]="writing || locked" /> I confirm this global engine change.</label>
          <div class="flex flex-wrap gap-2">
            <button type="button" (click)="apply()" [disabled]="!canApply" class="rounded bg-secondary px-4 py-2 font-semibold text-black disabled:opacity-50">{{writing?'Applying…':'Apply engine change'}}</button>
            <button type="button" (click)="cancel()" [disabled]="writing" class="rounded border border-white/20 px-4 py-2">Cancel</button>
          </div>
        </section>
      </ng-container>
    </section>
  `
})
export class SalesEngineControlComponent implements OnInit, OnChanges, OnDestroy {
  @Input() editor: SalesEngine = 'langgraph';
  @Input() refreshKey = 0;
  @Input() locked = false;
  @Output() selectionChanged = new EventEmitter<EngineStatus>();
  @Output() writingChange = new EventEmitter<boolean>();
  status: EngineStatus | null = null;
  pending: SalesEngine | null = null;
  note = ''; confirmed = false;
  loading = false; writing = false; error = ''; notice = '';
  private request?: Subscription;
  private generation = 0;
  private readonly url = `${API_V1_URL}/ai/hermes/engine`;
  constructor(private http: HttpClient, private cdr: ChangeDetectorRef) {}
  ngOnInit(): void { this.load(); }
  ngOnChanges(changes: SimpleChanges): void {
    if (changes['refreshKey'] && !changes['refreshKey'].firstChange) this.load();
  }
  ngOnDestroy(): void { this.generation++; this.request?.unsubscribe(); }
  name(engine: SalesEngine | null): string { return engine==='langgraph'?'LangGraph':engine==='hermes'?'Hermes':'None — review required'; }
  canSelect(engine: SalesEngine): boolean {
    const s = this.status;
    return !!s && s.selectable_engines?.includes(engine) === true && (engine !== 'hermes' || (s.hermes_live_ready && s.hermes_policy_published && s.hermes_policy_valid && s.hermes_policy_enabled));
  }
  blockReason(s: EngineStatus): string {
    if (!s.hermes_live_ready) return 'HEI-06/07 readiness gate is closed. Publishing a prompt cannot activate Hermes.';
    if (!s.hermes_policy_published || !s.hermes_policy_valid || !s.hermes_policy_enabled) return 'Publish a valid enabled Hermes policy before selecting this engine.';
    return 'Engine selection is unavailable. Refresh and review server status.';
  }
  cancel(): void { this.pending = null; this.note = ''; this.confirmed = false; }
  choose(engine: SalesEngine): void {
    if (this.loading || this.writing || this.locked || !this.canSelect(engine) || engine===this.status?.active_sales_engine) return;
    this.cancel(); this.pending = engine; this.notice = ''; this.error = '';
  }
  get canApply(): boolean {
    return !this.loading && !this.writing && !this.locked && !!this.pending && this.canSelect(this.pending) &&
      this.pending!==this.status?.active_sales_engine && this.confirmed && !!this.note.trim() && this.note.trim().length<=400;
  }
  load(preserveError = false): void {
    if (this.writing) return;
    this.request?.unsubscribe(); const id = ++this.generation;
    this.cancel(); this.status = null; this.loading = true;
    if (!preserveError) { this.error = ''; this.notice = ''; }
    this.request = this.http.get<EngineStatus>(this.url).subscribe({next: value => {
      if (id!==this.generation) return;
      this.status = value; this.loading = false; this.cdr.markForCheck();
    }, error: () => {
      if (id!==this.generation) return;
      this.status = null; this.loading = false;
      this.error = 'Routing status could not be verified. No engine change is allowed. Refresh and try again.';
      this.cdr.markForCheck();
    }});
  }
  apply(): void {
    if (!this.canApply || !this.pending || !this.status) return;
    const target = this.pending, snapshot = this.status;
    const payload = {active_sales_engine:target, change_note:this.note.trim(), expected_revision:snapshot.revision,
      expected_published_version_id:snapshot.published_version_id};
    this.writing = true; this.writingChange.emit(true); this.error = ''; this.notice = '';
    const id = ++this.generation;
    this.request = this.http.put<EngineStatus>(this.url,payload).subscribe({next: value => {
      if (id!==this.generation) return;
      this.writing = false; this.writingChange.emit(false); this.status = value; this.cancel();
      this.notice = value.active_sales_engine===target ? `Server recorded ${this.name(target)} as the selected engine. Check effective routing above.` : 'Server returned a different selection. Review current routing.';
      this.selectionChanged.emit(value); this.cdr.markForCheck();
    }, error: err => {
      if (id!==this.generation) return;
      this.writing = false; this.writingChange.emit(false);
      const code = err?.error?.detail?.code;
      this.error = code==='ENGINE_SELECTION_STALE'?'Routing or policy changed. Review refreshed status and confirm again.':
        code==='HERMES_NOT_READY'?'Hermes activation is blocked by the server. No engine change was applied.':
        'The engine change could not be verified. Review the refreshed server status before trying again.';
      this.load(true); this.cdr.markForCheck();
    }});
  }
}
