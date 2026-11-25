import { CommonModule } from '@angular/common';
import { ChangeDetectorRef, Component, OnInit } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { API_V1_URL } from '../../../core/config/api.config';

type HermesConfiguration = {
  engine: string; provider: string; language: 'en'; model: string;
  allowed_models: string[]; system_prompt: string; max_iterations: number;
  enabled_tools: string[]; enabled: boolean;
};
type Version = {id: string; version: number; change_note: string; created_at: string; is_published: boolean};

@Component({
  selector: 'app-hermes-sales-settings',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink],
  template: `
    <main class="bp-page">
      <div class="bp-page__container bp-page__container--form space-y-6">
        <header class="border-b border-white/10 pb-5">
          <a routerLink="/admin/ai-settings" class="text-sm text-secondary underline">AI Settings</a>
          <h1 class="mt-2 text-3xl font-light">Hermes <span class="text-secondary font-semibold">Sales Core</span></h1>
          <p class="mt-2 text-sm text-gray-400">One global configuration for every Company and Project · Staff Superadmin only · English only</p>
        </header>
        <section class="rounded-xl border border-amber-700/50 bg-amber-950/20 p-4 text-sm text-amber-100">
          <strong>Staged rollout (P05/P06).</strong> Publishing changes the Hermes global configuration registry,
          <strong>not</strong> the currently deployed sales engine. No live SMS, WhatsApp or appointment effects are enabled by this screen.
        </section>
        <p *ngIf="error" role="alert" class="rounded border border-red-700 p-3 text-red-300">{{ error }}</p>
        <p *ngIf="notice" role="status" class="rounded border border-gray-600 p-3">{{ notice }}</p>
        <p *ngIf="loading">Loading global configuration…</p>
        <ng-container *ngIf="!loading && config as cfg">
          <section class="rounded-xl border border-white/10 bg-white/5 p-5 space-y-4">
            <header class="flex flex-wrap items-center justify-between gap-3">
              <h2 class="text-lg font-semibold">Published configuration</h2>
              <span class="text-xs text-gray-400">Version {{ publishedVersionId || 'Built-in baseline (not published)' }}</span>
            </header>
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
              <textarea rows="3" [ngModel]="modelsText" (ngModelChange)="changeModels($event)"
                class="mt-1 w-full rounded border border-white/20 bg-black p-3 font-mono text-sm text-white"></textarea>
            </label>
            <label class="block text-xs text-gray-400">Global system prompt
              <textarea rows="16" [(ngModel)]="cfg.system_prompt"
                class="mt-1 w-full rounded border border-white/20 bg-black p-3 font-mono text-sm leading-relaxed text-white"></textarea>
            </label>
            <div>
              <h3 class="text-sm font-medium">Permitted business tools</h3>
              <p class="mb-3 text-xs text-gray-400">Disabling a tool removes an option. Authorization, tenant isolation, consent, bookings and materials approvals are enforced in backend code, not in this form.</p>
              <div class="grid gap-2 sm:grid-cols-2">
                <label *ngFor="let tool of availableTools" class="flex items-center gap-2 text-xs"><input type="checkbox" [checked]="hasTool(tool)" (change)="toggleTool(tool, $any($event.target).checked)" />{{ tool }}</label>
              </div>
            </div>
            <label class="flex items-center gap-2 text-sm">
              <input type="checkbox" [(ngModel)]="cfg.enabled" /> Permit this global configuration to be used at a future controlled Hermes cutover
            </label>
            <label class="block text-xs text-gray-400">Change note (required for publishing)
              <input [(ngModel)]="changeNote" maxlength="500" placeholder="Reason for this version" class="mt-1 w-full rounded border border-white/20 bg-black p-3 text-white" />
            </label>
            <div class="flex flex-wrap gap-3">
              <button type="button" [disabled]="busy" (click)="save(false)" class="rounded border border-white/30 px-4 py-2 disabled:opacity-50">Save draft</button>
              <button type="button" [disabled]="busy || !changeNote.trim()" (click)="save(true)" class="rounded bg-secondary px-4 py-2 font-semibold text-black disabled:opacity-50">Save and publish</button>
              <button type="button" [disabled]="busy" (click)="load()" class="rounded border border-white/10 px-4 py-2">Reload</button>
            </div>
          </section>
          <section class="rounded-xl border border-white/10 bg-white/5 p-5">
            <h2 class="mb-3 text-lg font-semibold">Global version history</h2>
            <p class="mb-3 text-xs text-gray-400">Restoration creates a new published version. Past records remain auditable. Configurations never contain credentials.</p>
            <p *ngIf="!versions.length" class="text-sm text-gray-400">No versions created yet.</p>
            <div *ngFor="let v of versions" class="flex flex-wrap items-center justify-between gap-3 border-t border-white/10 py-3">
              <div><strong>Version {{v.version}}</strong> <span class="text-xs text-gray-400">{{v.is_published ? '· Published' : '· Draft'}} · {{v.created_at | date:'medium'}}</span><p class="text-xs text-gray-400">{{v.change_note || 'No change note'}}</p></div>
              <div class="flex gap-2">
                <button type="button" [disabled]="busy" (click)="loadVersion(v)" class="rounded border px-3 py-1 text-xs">Edit copy</button>
                <button type="button" *ngIf="!v.is_published" [disabled]="busy" (click)="publish(v.id)" class="rounded bg-secondary px-3 py-1 text-xs text-black">Publish</button>
                <button type="button" *ngIf="!v.is_published" [disabled]="busy" (click)="restore(v.id)" class="rounded border px-3 py-1 text-xs">Restore as new</button>
              </div>
            </div>
          </section>
        </ng-container>
      </div>
    </main>
  `
})
export class HermesSalesSettingsComponent implements OnInit {
  config: HermesConfiguration | null = null;
  availableTools: string[] = [];
  versions: Version[] = [];
  publishedVersionId: string | null = null;
  loading = true; busy = false; error = ''; notice = ''; changeNote = '';
  private readonly url = `${API_V1_URL}/ai/hermes`;

  constructor(private http: HttpClient, private cdr: ChangeDetectorRef) {}
  ngOnInit(): void { this.load(); }
  get modelsText(): string { return (this.config?.allowed_models || []).join('\n'); }
  changeModels(value: string): void {
    if (!this.config) return;
    this.config.allowed_models = value.split('\n').map(x => x.trim()).filter(Boolean);
  }
  hasTool(tool: string): boolean { return !!this.config?.enabled_tools.includes(tool); }
  toggleTool(tool: string, checked: boolean): void {
    if (!this.config) return;
    this.config.enabled_tools = checked ? [...new Set([...this.config.enabled_tools, tool])] : this.config.enabled_tools.filter(x => x !== tool);
  }
  private fail(err: any): void {
    const detail = err?.error?.detail;
    this.error = typeof detail === 'string' ? detail : 'The requested configuration operation failed. Check inputs and try again.';
    this.busy = false; this.loading = false; this.cdr.markForCheck();
  }
  load(): void {
    this.loading = true; this.error = '';
    this.http.get<any>(`${this.url}/global`).subscribe({next: data => {
      this.config = data.configuration;
      this.availableTools = data.available_tools || [];
      this.publishedVersionId = data.published_version_id || null;
      this.loading = false; this.fetchVersions(); this.cdr.markForCheck();
    }, error: err => this.fail(err)});
  }
  private fetchVersions(): void {
    this.http.get<any>(`${this.url}/versions?page=1&page_size=50`).subscribe({next: data => {
      this.versions = data.items || []; this.cdr.markForCheck();
    }, error: err => this.fail(err)});
  }
  save(publishNow: boolean): void {
    if (this.busy || !this.config || (publishNow && !this.changeNote.trim())) return;
    this.busy = true; this.error = ''; this.notice = '';
    this.http.post<any>(`${this.url}/drafts`, {configuration: this.config, change_note: this.changeNote}).subscribe({
      next: version => {
        if (!publishNow) {this.busy = false; this.notice = `Draft ${version.version} saved.`; this.changeNote = ''; this.fetchVersions(); this.cdr.markForCheck(); return;}
        this.publish(version.id);
      }, error: err => this.fail(err)
    });
  }
  publish(id: string): void {
    this.busy = true;
    this.http.post(`${this.url}/versions/${encodeURIComponent(id)}/publish`, {}).subscribe({next: () => {
      this.busy = false; this.notice = 'Published globally. Live sales engine is unchanged until cutover.'; this.changeNote = ''; this.load();
    }, error: err => this.fail(err)});
  }
  restore(id: string): void {
    this.busy = true;
    this.http.post(`${this.url}/versions/${encodeURIComponent(id)}/restore`, {}).subscribe({next: () => {
      this.busy = false; this.notice = 'A new published version was created.'; this.load();
    }, error: err => this.fail(err)});
  }
  loadVersion(version: Version): void {
    this.busy = true;
    this.http.get<any>(`${this.url}/versions/${encodeURIComponent(version.id)}`).subscribe({next: data => {
      this.config = data.configuration; this.changeNote = `Based on version ${version.version}`;
      this.busy = false; this.notice = 'Historical configuration loaded into editor, not published.'; this.cdr.markForCheck();
    }, error: err => this.fail(err)});
  }
}
