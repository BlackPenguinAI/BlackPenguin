import { CommonModule } from '@angular/common';
import { ChangeDetectorRef, Component, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { HttpClient } from '@angular/common/http';
import { ActivatedRoute, RouterModule } from '@angular/router';

import { API_V1_URL } from '../../../core/config/api.config';

@Component({
  selector: 'app-marketing', standalone: true, imports: [CommonModule, FormsModule, RouterModule],
  templateUrl: './marketing.html',
})
export class MarketingComponent implements OnInit {
  projects: any[] = []; leads: any[] = []; projectId = ''; loading = true;
  summary: any = null; selectedCampaignId = ''; lockedProject = false;
  constructor(private http: HttpClient, private cdr: ChangeDetectorRef, private route: ActivatedRoute) {}
  ngOnInit(): void {
    const routeProjectId = this.route.snapshot.paramMap.get('id');
    this.lockedProject = !!routeProjectId;
    this.http.get<any[]>(`${API_V1_URL}/projects/`).subscribe(projects => {
      this.projects = projects;
      this.projectId = routeProjectId || projects[0]?.id || '';
      this.reload();
      this.cdr.markForCheck();
    });
  }
  reload(): void {
    if (!this.projectId) { this.leads = []; this.loading = false; return; }
    this.loading = true;
    this.http.get<any>(`${API_V1_URL}/projects/${this.projectId}/marketing/summary`).subscribe({
      next: summary => {
        this.summary = summary;
        this.leads = summary.leads;
        this.loading = false;
        this.cdr.markForCheck();
      },
      error: () => {
        this.loading = false;
        this.cdr.markForCheck();
      },
    });
  }
  count(stage: string): number { return this.leads.filter(lead => lead.funnel_stage === stage).length; }
  get visibleLeads(): any[] { return this.selectedCampaignId ? this.leads.filter(lead => lead.campaign_id === this.selectedCampaignId) : this.leads; }
}
