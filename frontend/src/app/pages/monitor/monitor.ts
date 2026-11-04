import { CommonModule, isPlatformBrowser } from '@angular/common';
import { Component, Inject, PLATFORM_ID, OnDestroy, isDevMode } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { HttpClient } from '@angular/common/http';
import { RouterLink } from '@angular/router';
import { Subscription } from 'rxjs';

@Component({
  selector: 'app-staff-monitor', standalone: true,
  imports: [CommonModule, FormsModule, RouterLink],
  templateUrl: './monitor.html',
})
export class StaffMonitorComponent implements OnDestroy {
  companies: any[] = []; projects: any[] = []; leads: any[] = []; conversations: any[] = [];
  company = ''; project = ''; lead = ''; conversation = '';
  messages: any[] = []; cursor = ''; paused = false; pauseReason = '';
  error = ''; busy = false; exporting = false; companiesMore = false; leadsMore = false;
  lastRefresh = ''; private generation = 0; private timer?: ReturnType<typeof setInterval>;
  private requests = new Subscription();
  private base = (isDevMode() ? 'http://localhost:8000' : '') + '/api/v1/monitor';
  constructor(private http: HttpClient, @Inject(PLATFORM_ID) platform: object) {
    if (isPlatformBrowser(platform)) {
      this.loadCompanies(); this.timer = setInterval(() => this.refresh(), 5000);
    }
  }
  ngOnDestroy() { if (this.timer) clearInterval(this.timer); this.requests.unsubscribe(); }
  private failed(error: any) {
    this.error = typeof error?.error?.detail === 'string' ? error.error.detail : 'Unable to load monitor. Check your staff session and retry.';
  }
  private get(path: string, apply: (data: any) => void) {
    const version = this.generation;
    this.requests.add(this.http.get(this.base + path).subscribe({ next: data => { if (version === this.generation) apply(data); }, error: e => { if (version === this.generation) this.failed(e); } }));
  }
  loadCompanies() {
    this.get('/companies?offset=' + this.companies.length, data => { this.companies.push(...data.items); this.companiesMore = data.has_more; });
  }
  private reset() { this.generation++; this.messages = []; this.cursor = ''; this.conversation = ''; this.conversations = []; this.error = ''; this.busy = false; this.exporting = false; this.paused = false; this.pauseReason = ''; this.lastRefresh = ''; }
  companyChanged() { this.reset(); this.project = ''; this.lead = ''; this.projects = []; this.leads = []; this.leadsMore = false; if (this.company) this.get('/projects?company_id=' + encodeURIComponent(this.company), d => this.projects = d); }
  projectChanged() { this.reset(); this.lead = ''; this.leads = []; this.leadsMore = false; if (this.project) this.loadLeads(); }
  loadLeads() { this.get('/leads?' + this.scope(false) + '&offset=' + this.leads.length, d => { this.leads.push(...d.items); this.leadsMore = d.has_more; }); }
  leadChanged() { this.reset(); if (this.lead) this.get('/conversations?' + this.scope(), d => this.conversations = d); }
  conversationChanged() { const selected = this.conversation; this.reset(); this.conversation = selected; this.get('/conversations?' + this.scope(), d => this.conversations = d); this.refresh(); }
  private scope(includeLead = true) { return new URLSearchParams({company_id: this.company, project_id: this.project, ...(includeLead ? {lead_id: this.lead} : {})}).toString(); }
  refresh() {
    if (!this.conversation || this.busy) return;
    this.busy = true; const version = this.generation;
    const url = `${this.base}/conversations/${encodeURIComponent(this.conversation)}?${this.scope()}${this.cursor ? '&after=' + encodeURIComponent(this.cursor) : ''}`;
    this.requests.add(this.http.get<any>(url).subscribe({ next: d => {
      if (version !== this.generation) return;
      const existing = new Set(this.messages.map(m => m.id));
      this.messages.push(...d.messages.filter((m: any) => !existing.has(m.id)));
      const statuses = new Map(d.delivery_statuses.map((m: any) => [m.message_id, m.status]));
      this.messages.forEach(m => { if (statuses.has(m.id)) m.status = statuses.get(m.id); });
      this.cursor = d.next_cursor || ''; this.paused = d.is_paused; this.pauseReason = d.pause_reason || '';
      this.lastRefresh = new Date().toISOString(); this.error = ''; this.busy = false;
      if (d.has_more) this.refresh();
    }, error: e => { if (version === this.generation) { this.busy = false; this.failed(e); } } }));
  }
  download() {
    if (!this.conversation || this.exporting) return;
    const version = this.generation; this.exporting = true;
    this.requests.add(this.http.get(`${this.base}/conversations/${encodeURIComponent(this.conversation)}/export?${this.scope()}`, {responseType:'blob'}).subscribe({ next: blob => {
      if (version !== this.generation) return; this.exporting = false;
      const url = URL.createObjectURL(blob); const a = document.createElement('a'); a.href = url; a.download = `chat-${this.conversation}.json`; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    }, error: e => { if (version === this.generation) { this.exporting = false; this.failed(e); } } }));
  }
}
