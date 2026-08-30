import { CommonModule } from '@angular/common';
import { ChangeDetectorRef, Component, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { HttpClient } from '@angular/common/http';
import { RouterModule } from '@angular/router';
import { API_V1_URL } from '../../../core/config/api.config';

@Component({ selector: 'app-leads', standalone: true, imports: [CommonModule, FormsModule, RouterModule], templateUrl: './leads.html', styleUrls: ['./leads.scss'] })
export class LeadsComponent implements OnInit {
  projects: any[] = []; leads: any[] = []; selected: any = null;
  projectId = ''; tier = ''; segment = ''; stage = ''; search = '';
  loading = true; detailLoading = false; error = '';
  readonly segments = ['first_time_buyer','move_up_buyer','relocation','downsizing','rental_yield_investor','appreciation_resale_investor','portfolio_diversification'];
  readonly stages = ['S00_CAPTURE','S01_RESEARCH','S02_QUALIFICATION','S03_PROBLEM_SOLUTION','S04_SCORING','S05_SEGMENTATION','S06_NURTURE','S07_OBJECTION','S08_APPOINTMENT','S09_HANDOFF'];
  constructor(private http: HttpClient, private cdr: ChangeDetectorRef) {}
  ngOnInit(): void { this.loadProjects(); this.reload(); }
  loadProjects(): void { this.http.get<any[]>(`${API_V1_URL}/projects/`).subscribe(rows => { this.projects = rows || []; this.cdr.markForCheck(); }); }
  reload(): void {
    this.loading = true; this.error = ''; const params = new URLSearchParams();
    if (this.projectId) params.set('project_id', this.projectId); if (this.tier) params.set('tier', this.tier);
    if (this.segment) params.set('segment', this.segment); if (this.stage) params.set('stage', this.stage);
    this.http.get<any[]>(`${API_V1_URL}/sales/leads?${params}`).subscribe({ next: rows => { this.leads = rows || []; this.loading = false; this.cdr.markForCheck(); }, error: err => { this.loading = false; this.error = err.error?.detail || 'Leads could not be loaded.'; this.cdr.markForCheck(); } });
  }
  open(lead: any): void { this.detailLoading = true; this.http.get<any>(`${API_V1_URL}/sales/leads/${lead.id}`).subscribe({ next: row => { this.selected = row; this.detailLoading = false; this.cdr.markForCheck(); }, error: err => { this.detailLoading = false; this.error = err.error?.detail || 'Lead detail could not be loaded.'; } }); }
  get visible(): any[] { const term = this.search.trim().toLowerCase(); return this.leads.filter(row => !term || `${row.full_name} ${row.email || ''} ${row.phone}`.toLowerCase().includes(term)); }
  score(lead: any): number { return Math.round(Number(lead.intent_score || 0) * 100); }
  label(value: string): string { return String(value || 'Not assigned').replaceAll('_', ' ').replace(/^./, c => c.toUpperCase()); }
  objectEntries(value: any): {key:string,value:any}[] { return Object.entries(value || {}).map(([key,item]) => ({ key, value: typeof item === 'object' ? JSON.stringify(item) : item })); }
}
