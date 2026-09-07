import { CommonModule } from '@angular/common';
import { ChangeDetectorRef, Component, OnDestroy, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { HttpClient } from '@angular/common/http';
import { Router, RouterModule } from '@angular/router';
import { finalize } from 'rxjs';
import { API_V1_URL } from '../../../core/config/api.config';

interface LeadDataRow {
  label: string;
  value: string;
  depth: number;
  group: boolean;
}

@Component({ selector: 'app-leads', standalone: true, imports: [CommonModule, FormsModule, RouterModule], templateUrl: './leads.html', styleUrls: ['./leads.scss'] })
export class LeadsComponent implements OnInit, OnDestroy {
  projects: any[] = []; leads: any[] = []; selected: any = null;
  projectId = ''; tier = ''; segment = ''; stage = ''; search = '';
  loading = true; detailLoading = false; exporting = false; downloadingSource = false; error = '';
  private pollTimer?: ReturnType<typeof setTimeout>;
  private polling = false;
  private pollingEnabled = false;
  private snapshotReady = false;
  private knownLeadIds = new Set<string>();
  private pendingMetaLeadId = '';
  readonly segments = ['first_time_buyer','move_up_buyer','relocation','downsizing','rental_yield_investor','appreciation_resale_investor','portfolio_diversification'];
  readonly stages = ['S00_CAPTURE','S01_RESEARCH','S02_QUALIFICATION','S03_PROBLEM_SOLUTION','S04_SCORING','S05_SEGMENTATION','S06_NURTURE','S07_OBJECTION','S08_APPOINTMENT','S09_HANDOFF'];
  constructor(private http: HttpClient, private cdr: ChangeDetectorRef, private router: Router) {}
  ngOnInit(): void { this.pollingEnabled = true; this.loadProjects(); this.reload(); }
  ngOnDestroy(): void { this.pollingEnabled = false; if (this.pollTimer) clearTimeout(this.pollTimer); }
  loadProjects(): void { this.http.get<any[]>(`${API_V1_URL}/projects/`).subscribe(rows => { this.projects = rows || []; this.cdr.markForCheck(); }); }
  reload(): void {
    this.loading = true; this.error = ''; const params = this.filterParams(false);
    this.http.get<any[]>(`${API_V1_URL}/sales/leads?${params}`).subscribe({ next: rows => { this.leads = rows || []; this.rememberLeads(this.leads); this.loading = false; this.cdr.markForCheck(); this.schedulePoll(); }, error: err => { this.loading = false; this.error = err.error?.detail || 'Leads could not be loaded.'; this.cdr.markForCheck(); this.schedulePoll(); } });
  }
  open(lead: any): void { this.pendingMetaLeadId = ''; this.loadDetail(lead.id, false); }

  private schedulePoll(): void {
    if (!this.pollingEnabled) return;
    if (this.pollTimer) clearTimeout(this.pollTimer);
    this.pollTimer = setTimeout(() => this.pollLeads(), 2000);
  }

  private pollLeads(): void {
    if (this.polling || (typeof document !== 'undefined' && document.hidden)) {
      this.schedulePoll();
      return;
    }
    this.polling = true;
    const params = this.filterParams(false);
    this.http.get<any[]>(`${API_V1_URL}/sales/leads?${params}`).subscribe({
      next: rows => {
        const incoming = this.snapshotReady
          ? (rows || []).find((row: any) => row.platform === 'meta' && !this.knownLeadIds.has(row.id))
          : null;
        this.leads = rows || [];
        this.rememberLeads(this.leads);
        if (incoming) {
          this.pendingMetaLeadId = incoming.id;
          this.loadDetail(incoming.id, true);
        } else if (this.pendingMetaLeadId && !this.detailLoading) {
          this.loadDetail(this.pendingMetaLeadId, true);
        }
        this.polling = false;
        this.cdr.markForCheck();
        this.schedulePoll();
      },
      error: () => { this.polling = false; this.schedulePoll(); },
    });
  }

  private loadDetail(leadId: string, openConversation: boolean): void {
    this.detailLoading = true;
    this.http.get<any>(`${API_V1_URL}/sales/leads/${leadId}`).subscribe({
      next: row => {
        this.selected = row;
        this.detailLoading = false;
        if (openConversation && row.conversation_id) {
          this.pendingMetaLeadId = '';
          void this.router.navigate(['/app/agent'], { queryParams: { project: row.project_id, lead: row.id } });
        }
        this.cdr.markForCheck();
      },
      error: err => {
        this.detailLoading = false;
        if (!openConversation) this.error = err.error?.detail || 'Lead detail could not be loaded.';
        this.cdr.markForCheck();
      },
    });
  }

  private rememberLeads(rows: any[]): void {
    rows.forEach(row => this.knownLeadIds.add(row.id));
    this.snapshotReady = true;
  }
  get visible(): any[] { const term = this.search.trim().toLowerCase(); return this.leads.filter(row => !term || `${row.full_name} ${row.email || ''} ${row.phone}`.toLowerCase().includes(term)); }
  score(lead: any): number { return Math.round(Number(lead.intent_score || 0) * 100); }
  label(value: string): string { return String(value || 'Not assigned').replaceAll('_', ' ').replace(/^./, c => c.toUpperCase()); }

  dataRows(value: unknown): LeadDataRow[] {
    const rows: LeadDataRow[] = [];
    const walk = (node: unknown, key: string, depth: number): void => {
      if (Array.isArray(node)) {
        rows.push({ label: this.label(key), value: node.length ? `${node.length} item(s)` : 'No values', depth, group: true });
        node.forEach((item, index) => walk(item, `Item ${index + 1}`, depth + 1));
        return;
      }
      if (node !== null && typeof node === 'object') {
        const entries = Object.entries(node as Record<string, unknown>);
        rows.push({ label: this.label(key), value: entries.length ? '' : 'No values', depth, group: true });
        entries.forEach(([childKey, child]) => walk(child, childKey, depth + 1));
        return;
      }
      rows.push({ label: this.label(key), value: this.displayValue(key, node), depth, group: false });
    };
    Object.entries((value && typeof value === 'object' ? value : {}) as Record<string, unknown>)
      .forEach(([key, item]) => walk(item, key, 0));
    return rows;
  }

  displayValue(key: string, value: unknown): string {
    if (value === null || value === undefined || value === '') return 'Not provided';
    if (typeof value === 'boolean') return value ? 'Yes' : 'No';
    if (typeof value === 'number') return new Intl.NumberFormat('en-US', { maximumFractionDigits: 2 }).format(value);
    const text = String(value);
    if (/(date|_at|timeline)/i.test(key) && /^\d{4}-\d{2}-\d{2}T/.test(text)) {
      const date = new Date(text);
      if (!Number.isNaN(date.getTime())) return date.toLocaleString();
    }
    return text;
  }

  structuredSummary(value: unknown): Record<string, unknown> | null {
    if (typeof value !== 'string' || !value.trim().startsWith('{')) return null;
    try {
      const parsed = JSON.parse(value);
      return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : null;
    } catch {
      return null;
    }
  }

  leadKind(lead: any): string {
    if (lead?.is_demo) return 'SIMULATION';
    if (lead?.is_test) return 'META TEST';
    if (lead?.platform === 'meta') return 'META LIVE';
    return 'MANUAL';
  }

  exportCurrentView(): void {
    if (this.exporting) return;
    this.exporting = true;
    this.error = '';
    const params = this.filterParams(true);
    this.http.get(`${API_V1_URL}/sales/leads/export.csv?${params}`, { responseType: 'blob' })
      .pipe(finalize(() => { this.exporting = false; this.cdr.markForCheck(); }))
      .subscribe({
        next: blob => this.saveBlob(blob, `black-penguin-leads-${new Date().toISOString().slice(0, 10)}.csv`),
        error: err => { this.error = err.error?.detail || 'The Lead report could not be downloaded.'; },
      });
  }

  downloadSourceData(): void {
    if (!this.selected?.id || this.downloadingSource) return;
    this.downloadingSource = true;
    this.error = '';
    const leadId = this.selected.id;
    this.http.get(`${API_V1_URL}/sales/leads/${leadId}/export.json`, { responseType: 'blob' })
      .pipe(finalize(() => { this.downloadingSource = false; this.cdr.markForCheck(); }))
      .subscribe({
        next: blob => this.saveBlob(blob, `black-penguin-lead-${leadId}.json`),
        error: err => { this.error = err.error?.detail || 'The Lead Record could not be downloaded.'; },
      });
  }

  private filterParams(includeSearch: boolean): URLSearchParams {
    const params = new URLSearchParams();
    if (this.projectId) params.set('project_id', this.projectId);
    if (this.tier) params.set('tier', this.tier);
    if (this.segment) params.set('segment', this.segment);
    if (this.stage) params.set('stage', this.stage);
    if (includeSearch && this.search.trim()) params.set('search', this.search.trim());
    return params;
  }

  private saveBlob(blob: Blob, filename: string): void {
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = filename;
    anchor.click();
    URL.revokeObjectURL(url);
  }
}
