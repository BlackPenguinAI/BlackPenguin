import { CommonModule } from '@angular/common';
import { ChangeDetectorRef, Component, OnInit, OnDestroy } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { HttpClient } from '@angular/common/http';
import { ActivatedRoute, RouterModule } from '@angular/router';

import { API_V1_URL } from '../../../core/config/api.config';
import { Subscription } from 'rxjs';

@Component({
  selector: 'app-marketing', standalone: true, imports: [CommonModule, FormsModule, RouterModule],
  templateUrl: './marketing.html', styleUrls: ['./marketing.scss'],
})
export class MarketingComponent implements OnInit, OnDestroy {
  projects: any[] = []; leads: any[] = []; projectId = ''; loading = true;
  summary: any = null; selectedCampaignId = ''; lockedProject = false;
  leadView = 'high'; search = '';
  error=''; private request?:Subscription; private projectsRequest?:Subscription; private generation=0;
  constructor(private http: HttpClient, private cdr: ChangeDetectorRef, private route: ActivatedRoute) {}
  ngOnInit(): void {
    const routeProjectId = this.route.snapshot.paramMap.get('id');
    this.lockedProject = !!routeProjectId;
    this.projectsRequest=this.http.get<any[]>(`${API_V1_URL}/projects/`).subscribe({next:projects => {
      this.projects = projects;
      this.projectId = routeProjectId || projects[0]?.id || '';
      this.reload();
      this.cdr.markForCheck();
    },error:()=>{this.loading=false;this.error='Projects could not be loaded. Refresh this page to retry.';this.cdr.markForCheck();}});
  }
  ngOnDestroy():void {this.generation++;this.request?.unsubscribe();this.projectsRequest?.unsubscribe();}
  reload(): void {
    this.request?.unsubscribe();const generation=++this.generation;const projectId=this.projectId;
    this.summary=null;this.leads=[];this.selectedCampaignId='';this.error='';
    if (!projectId) { this.loading = false; return; }
    this.loading = true;
    this.request=this.http.get<any>(`${API_V1_URL}/projects/${encodeURIComponent(projectId)}/marketing/summary`).subscribe({
      next: summary => {
        if(generation!==this.generation || this.projectId!==projectId)return;
        this.summary = summary;
        this.leads = summary.leads;
        this.loading = false;
        this.cdr.markForCheck();
      },
      error: () => {
        if(generation!==this.generation)return;
        this.error='Marketing and Meta status could not be loaded. No setup changes were made. Retry.';
        this.loading = false;
        this.cdr.markForCheck();
      },
    });
  }
  get accountLabel():string {return ({connected:'Account authorized',permissions_required:'Account connected · permissions missing',reconnect_required:'Account expired or inactive · reconnect required',not_connected:'No Meta account connected'} as Record<string,string>)[this.summary?.meta_setup?.account_status] || 'Account status unavailable';}
  get routingLabel():string {return ({connected:'Active Project route verified',review_required:'Saved campaigns or forms require review',not_linked:'No Meta campaigns or forms linked to this Project'} as Record<string,string>)[this.summary?.meta_setup?.routing_status] || 'Project routing status unavailable';}
  mappingReason(reason:string):string {return ({ready:'Ready for live leads',inactive_campaign:'Campaign is not active',connection_required:'Connection required',real_verification_required:'Real verification required',connection_expired:'Connection expired',authorization_required:'Account authorization or permissions require review',page_or_form_required:'Page or lead form is missing'} as Record<string,string>)[reason] || 'Review required';}
  count(stage: string): number { return this.leads.filter(lead => lead.funnel_stage === stage).length; }
  asUtc(value:string):string {return /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?$/.test(value) ? value+'Z' : value;}
  get visibleLeads(): any[] {
    const term = this.search.trim().toLowerCase();
    return this.leads.filter(lead => (!this.selectedCampaignId || lead.campaign_id === this.selectedCampaignId)
      && (this.leadView === 'all' || (this.leadView === 'high' ? lead.intent_score >= .75 : lead.funnel_stage === 'closed'))
      && (!term || `${lead.full_name} ${lead.email || ''}`.toLowerCase().includes(term)));
  }
  initials(name: string): string { return name.split(/\s+/).slice(0,2).map(x => x[0]).join('').toUpperCase(); }
}
