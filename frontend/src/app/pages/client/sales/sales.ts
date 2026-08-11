import { CommonModule } from '@angular/common';
import { Component, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { HttpClient } from '@angular/common/http';

import { API_V1_URL } from '../../../core/config/api.config';

@Component({ selector: 'app-sales', standalone: true, imports: [CommonModule, FormsModule], templateUrl: './sales.html' })
export class SalesComponent implements OnInit {
  projects: any[] = []; meetings: any[] = []; leads: any[] = []; projectId = ''; loading = true;
  simulation = { lead_id: '', message: '' }; result: any = null; simulating = false;
  constructor(private http: HttpClient) {}
  ngOnInit(): void { this.http.get<any[]>(`${API_V1_URL}/projects/`).subscribe(projects => { this.projects = projects; this.projectId = projects[0]?.id || ''; this.reload(); }); }
  reload(): void {
    if (!this.projectId) { this.loading = false; return; }
    this.loading = true;
    this.http.get<any[]>(`${API_V1_URL}/sales/projects/${this.projectId}/meetings`).subscribe({ next: meetings => { this.meetings = meetings; this.loading = false; }, error: () => this.loading = false });
    this.http.get<any[]>(`${API_V1_URL}/sales/projects/${this.projectId}/leads-report`).subscribe(leads => { this.leads = leads; this.simulation.lead_id = leads[0]?.id || ''; });
  }
  simulate(): void {
    if (!this.simulation.lead_id || !this.simulation.message) return;
    this.simulating = true; this.result = null;
    this.http.post(`${API_V1_URL}/sales-agent/simulate`, this.simulation).subscribe({ next: result => { this.result = result; this.simulating = false; }, error: err => { this.result = { error: err.error?.detail || 'Simulation failed' }; this.simulating = false; } });
  }
}
