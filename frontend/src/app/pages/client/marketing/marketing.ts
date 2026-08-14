import { CommonModule } from '@angular/common';
import { ChangeDetectorRef, Component, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { HttpClient } from '@angular/common/http';
import { ActivatedRoute, RouterModule } from '@angular/router';

import { API_V1_URL } from '../../../core/config/api.config';

@Component({
  selector: 'app-marketing', standalone: true, imports: [CommonModule, FormsModule, RouterModule],
  templateUrl: './marketing.html', styleUrls: ['./marketing.scss'],
})
export class MarketingComponent implements OnInit {
  projects: any[] = []; leads: any[] = []; projectId = ''; loading = true;
  summary: any = null; selectedCampaignId = ''; lockedProject = false;
  leadView = 'high'; search = '';
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
  get visibleLeads(): any[] {
    const term = this.search.trim().toLowerCase();
    return this.leads.filter(lead => (!this.selectedCampaignId || lead.campaign_id === this.selectedCampaignId)
      && (this.leadView === 'all' || (this.leadView === 'high' ? lead.intent_score >= .75 : lead.funnel_stage === 'closed'))
      && (!term || `${lead.full_name} ${lead.email || ''}`.toLowerCase().includes(term)));
  }
  initials(name: string): string { return name.split(/\s+/).slice(0,2).map(x => x[0]).join('').toUpperCase(); }
}
