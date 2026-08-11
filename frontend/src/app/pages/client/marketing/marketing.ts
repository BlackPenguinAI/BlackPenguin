import { CommonModule } from '@angular/common';
import { Component, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { HttpClient } from '@angular/common/http';

import { API_V1_URL } from '../../../core/config/api.config';

@Component({
  selector: 'app-marketing', standalone: true, imports: [CommonModule, FormsModule],
  templateUrl: './marketing.html',
})
export class MarketingComponent implements OnInit {
  projects: any[] = []; leads: any[] = []; projectId = ''; loading = true;
  constructor(private http: HttpClient) {}
  ngOnInit(): void {
    this.http.get<any[]>(`${API_V1_URL}/projects/`).subscribe(projects => {
      this.projects = projects; this.projectId = projects[0]?.id || ''; this.reload();
    });
  }
  reload(): void {
    if (!this.projectId) { this.leads = []; this.loading = false; return; }
    this.loading = true;
    this.http.get<any[]>(`${API_V1_URL}/sales/projects/${this.projectId}/leads-report`).subscribe({ next: leads => { this.leads = leads; this.loading = false; }, error: () => this.loading = false });
  }
  count(stage: string): number { return this.leads.filter(lead => lead.funnel_stage === stage).length; }
}
