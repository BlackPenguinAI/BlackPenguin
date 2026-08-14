import { CommonModule } from '@angular/common';
import { ChangeDetectorRef, Component, ElementRef, OnInit, ViewChild } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { HttpClient } from '@angular/common/http';
import { ActivatedRoute } from '@angular/router';
import { forkJoin } from 'rxjs';
import { API_V1_URL } from '../../../core/config/api.config';

@Component({ selector: 'app-agent', standalone: true, imports: [CommonModule, FormsModule], templateUrl: './agent.html', styleUrls: ['./agent.scss'] })
export class AgentComponent implements OnInit {
  @ViewChild('thread') thread?: ElementRef<HTMLElement>;
  projects: any[] = []; conversations: any[] = []; messages: any[] = [];
  projectId = ''; selected: any = null; loading = true; loadingMessages = false; sending = false;
  search = ''; filter = 'all'; draft = ''; error = '';
  constructor(private http: HttpClient, private cdr: ChangeDetectorRef, private route: ActivatedRoute) {}
  ngOnInit(): void {
    this.http.get<any[]>(`${API_V1_URL}/projects/`).subscribe({ next: projects => {
      this.projects = projects; this.projectId = this.route.snapshot.queryParamMap.get('project') || projects.find(p => p.is_demo)?.id || projects[0]?.id || '';
      this.loadConversations();
    }, error: () => { this.loading = false; this.error = 'Projects could not be loaded.'; this.cdr.markForCheck(); }});
  }
  loadConversations(keep = false): void {
    if (!this.projectId) { this.loading = false; return; }
    this.loading = true; this.error = '';
    this.http.get<any[]>(`${API_V1_URL}/sales-agent/conversations?project_id=${encodeURIComponent(this.projectId)}`).subscribe({
      next: rows => {
        this.conversations = rows; const requested = this.route.snapshot.queryParamMap.get('lead');
        const next = keep ? rows.find(row => row.id === this.selected?.id) : rows.find(row => row.lead_id === requested) || rows[0];
        this.loading = false; next ? this.select(next) : (this.selected = null); this.cdr.markForCheck();
      }, error: err => { this.loading = false; this.error = err.error?.detail || 'Conversations could not be loaded.'; this.cdr.markForCheck(); }
    });
  }
  select(conversation: any): void {
    this.selected = conversation; this.loadingMessages = true; this.messages = []; this.error = '';
    this.http.get<any[]>(`${API_V1_URL}/sales-agent/conversations/${conversation.id}/messages`).subscribe({
      next: rows => { this.messages = rows; this.loadingMessages = false; this.cdr.markForCheck(); setTimeout(() => this.scrollEnd()); },
      error: () => { this.loadingMessages = false; this.error = 'The conversation could not be loaded.'; this.cdr.markForCheck(); }
    });
  }
  send(): void {
    const message = this.draft.trim(); if (!message || !this.selected || this.sending || this.selected.is_paused) return;
    this.sending = true; this.error = '';
    this.http.post(`${API_V1_URL}/sales-agent/simulate`, { lead_id: this.selected.lead_id, message }).subscribe({
      next: () => { this.draft = ''; this.sending = false; this.loadConversations(true); },
      error: err => { this.sending = false; this.error = err.error?.detail || 'The simulated turn could not be completed.'; this.cdr.markForCheck(); }
    });
  }
  action(action: 'pause'|'resume'|'human_handoff'): void {
    if (!this.selected) return;
    this.http.post<any>(`${API_V1_URL}/sales-agent/conversations/${this.selected.id}/action`, { action }).subscribe({ next: row => { this.selected = row; this.loadConversations(true); }, error: err => { this.error = err.error?.detail || 'The action could not be saved.'; this.cdr.markForCheck(); }});
  }
  get visible(): any[] {
    const term = this.search.trim().toLowerCase();
    return this.conversations.filter(row => (this.filter === 'all' || (this.filter === 'active' ? !row.is_paused : row.is_paused)) && (!term || `${row.lead_name} ${row.phone} ${row.last_message}`.toLowerCase().includes(term)));
  }
  initials(name: string): string { return name.split(/\s+/).slice(0,2).map(x => x[0]).join('').toUpperCase(); }
  private scrollEnd(): void { const node = this.thread?.nativeElement; if (node) node.scrollTop = node.scrollHeight; }
}
