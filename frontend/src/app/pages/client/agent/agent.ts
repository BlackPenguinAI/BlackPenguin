import { CommonModule } from '@angular/common';
import { ChangeDetectorRef, Component, ElementRef, OnInit, ViewChild } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { HttpClient } from '@angular/common/http';
import { ActivatedRoute } from '@angular/router';
import { API_V1_URL } from '../../../core/config/api.config';

@Component({
  selector: 'app-agent',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './agent.html',
  styleUrls: ['./agent.scss'],
})
export class AgentComponent implements OnInit {
  @ViewChild('thread') thread?: ElementRef<HTMLElement>;
  options: any[] = []; conversations: any[] = []; messages: any[] = []; slots: any[] = [];
  projectId = ''; campaignId = ''; selected: any = null; selectedSlot = '';
  loading = true; loadingMessages = false; sending = false; creating = false;
  advancing = false; confirming = false; setupOpen = true;
  search = ''; filter = 'all'; draft = ''; error = ''; success = '';
  form = { full_name: '', phone: '', email: '', product_interest: '', budget: '', purchase_timeline: '', consent: false };

  constructor(private http: HttpClient, private cdr: ChangeDetectorRef, private route: ActivatedRoute) {}

  ngOnInit(): void { this.loadOptions(); }

  loadOptions(): void {
    this.loading = true; this.error = '';
    this.http.get<any[]>(`${API_V1_URL}/sales-agent/simulation-options`).subscribe({
      next: rows => {
        this.options = rows;
        const requested = this.route.snapshot.queryParamMap.get('project');
        this.projectId = rows.find(row => row.id === requested)?.id || rows[0]?.id || '';
        this.campaignId = this.campaigns[0]?.id || '';
        this.loadConversations();
      },
      error: err => { this.loading = false; this.error = err.error?.detail || 'Simulation projects could not be loaded.'; this.cdr.markForCheck(); },
    });
  }

  projectChanged(): void {
    this.campaignId = this.campaigns[0]?.id || ''; this.selected = null; this.messages = []; this.slots = [];
    this.loadConversations();
  }

  get campaigns(): any[] { return this.options.find(row => row.id === this.projectId)?.campaigns || []; }
  get currentProject(): any { return this.options.find(row => row.id === this.projectId); }
  get formComplete(): boolean {
    return !!(this.projectId && this.campaignId && this.form.full_name.trim() && this.form.phone.trim() && this.form.consent);
  }

  loadConversations(keep = false, preferredConversationId = ''): void {
    if (!this.projectId) { this.loading = false; this.conversations = []; return; }
    this.loading = true; this.error = '';
    this.http.get<any[]>(`${API_V1_URL}/sales-agent/conversations?project_id=${encodeURIComponent(this.projectId)}`).subscribe({
      next: rows => {
        this.conversations = rows;
        const requestedLead = this.route.snapshot.queryParamMap.get('lead');
        const next = rows.find(row => row.id === preferredConversationId)
          || (keep ? rows.find(row => row.id === this.selected?.id) : null)
          || rows.find(row => row.lead_id === requestedLead) || rows[0];
        this.loading = false; this.setupOpen = !next; next ? this.select(next) : (this.selected = null); this.cdr.markForCheck();
      },
      error: err => { this.loading = false; this.error = err.error?.detail || 'Conversations could not be loaded.'; this.cdr.markForCheck(); },
    });
  }

  startSimulation(): void {
    if (!this.formComplete || this.creating) return;
    this.creating = true; this.error = ''; this.success = '';
    this.http.post<any>(`${API_V1_URL}/sales-agent/simulations`, {
      project_id: this.projectId, campaign_id: this.campaignId,
      lead: {
        ...this.form,
        email: this.form.email.trim() || null,
        product_interest: this.form.product_interest.trim() || null,
        budget: this.form.budget.trim() || null,
        purchase_timeline: this.form.purchase_timeline.trim() || null,
        custom_answers: {},
      },
    }).subscribe({
      next: result => {
        this.creating = false; this.setupOpen = false;
        this.success = 'Simulation created. The first SMS follows the active Sales Agent prompt.';
        this.resetForm(); this.loadConversations(false, result.conversation_id);
      },
      error: err => {
        this.creating = false;
        this.error = err.error?.detail || this.validationMessage(err.error) || 'The simulation could not be created.';
        this.cdr.markForCheck();
      },
    });
  }

  select(conversation: any): void {
    this.selected = conversation; this.setupOpen = false; this.loadingMessages = true;
    this.messages = []; this.slots = []; this.selectedSlot = ''; this.error = '';
    this.http.get<any[]>(`${API_V1_URL}/sales-agent/conversations/${conversation.id}/messages`).subscribe({
      next: rows => {
        this.messages = rows; this.loadingMessages = false; this.cdr.markForCheck();
        setTimeout(() => this.scrollEnd()); if (conversation.simulation_id && !conversation.appointment_id) this.loadSlots();
      },
      error: () => { this.loadingMessages = false; this.error = 'The conversation could not be loaded.'; this.cdr.markForCheck(); },
    });
  }

  send(): void {
    const message = this.draft.trim(); if (!message || !this.selected || this.sending || this.selected.is_paused) return;
    this.sending = true; this.error = '';
    this.http.post(`${API_V1_URL}/sales-agent/simulate`, { lead_id: this.selected.lead_id, message }).subscribe({
      next: () => { this.draft = ''; this.sending = false; this.loadConversations(true); },
      error: err => { this.sending = false; this.error = err.error?.detail || 'The simulated turn could not be completed.'; this.cdr.markForCheck(); },
    });
  }

  loadSlots(): void {
    if (!this.selected?.simulation_id) return;
    this.http.get<any[]>(`${API_V1_URL}/sales-agent/simulations/${this.selected.simulation_id}/slots`).subscribe({
      next: rows => { this.slots = rows; if (!rows.find(row => row.start_at === this.selectedSlot)) this.selectedSlot = ''; this.cdr.markForCheck(); },
      error: err => { this.slots = []; this.error = err.error?.detail || 'Available appointment times could not be loaded.'; this.cdr.markForCheck(); },
    });
  }

  confirmSlot(): void {
    if (!this.selected?.simulation_id || !this.selectedSlot || this.confirming) return;
    this.confirming = true; this.error = '';
    this.http.post<any>(`${API_V1_URL}/sales-agent/simulations/${this.selected.simulation_id}/appointments`, {
      start_at: this.selectedSlot, duration_minutes: 45, modality: 'virtual',
    }).subscribe({
      next: result => { this.confirming = false; this.success = `Appointment assigned to ${result.assigned_sales_name}.`; this.loadConversations(true); },
      error: err => { this.confirming = false; this.error = err.error?.detail || 'The appointment could not be confirmed.'; this.loadSlots(); },
    });
  }

  advance(hours: number): void {
    if (!this.selected?.simulation_id || this.advancing) return;
    this.advancing = true; this.error = '';
    this.http.post<any>(`${API_V1_URL}/sales-agent/simulations/${this.selected.simulation_id}/advance`, { hours }).subscribe({
      next: result => {
        this.advancing = false;
        this.success = result.processed_follow_ups ? `${result.processed_follow_ups} scheduled follow-up was generated.` : 'Virtual time advanced. No follow-up was due.';
        this.loadConversations(true);
      },
      error: err => { this.advancing = false; this.error = err.error?.detail || 'Virtual time could not be advanced.'; this.cdr.markForCheck(); },
    });
  }

  approve(status: 'approved' | 'changes_requested'): void {
    if (!this.selected?.simulation_id) return;
    this.http.put(`${API_V1_URL}/sales-agent/simulations/${this.selected.simulation_id}/approval`, { status, notes: null }).subscribe({
      next: () => { this.success = status === 'approved' ? 'This protocol test was approved.' : 'Changes were requested for this protocol test.'; this.loadConversations(true); },
      error: err => { this.error = err.error?.detail || 'The review could not be saved.'; this.cdr.markForCheck(); },
    });
  }

  action(action: 'pause' | 'resume' | 'human_handoff'): void {
    if (!this.selected) return;
    this.http.post<any>(`${API_V1_URL}/sales-agent/conversations/${this.selected.id}/action`, { action }).subscribe({
      next: row => { this.selected = row; this.loadConversations(true); },
      error: err => { this.error = err.error?.detail || 'The action could not be saved.'; this.cdr.markForCheck(); },
    });
  }

  get visible(): any[] {
    const term = this.search.trim().toLowerCase();
    return this.conversations.filter(row => (this.filter === 'all' || (this.filter === 'active' ? !row.is_paused : row.is_paused)) && (!term || `${row.lead_name} ${row.phone} ${row.last_message}`.toLowerCase().includes(term)));
  }
  initials(name: string): string { return name.split(/\s+/).slice(0, 2).map(value => value[0]).join('').toUpperCase(); }
  private resetForm(): void { this.form = { full_name: '', phone: '', email: '', product_interest: '', budget: '', purchase_timeline: '', consent: false }; }
  private validationMessage(error: any): string { return Array.isArray(error?.detail) ? error.detail.map((item: any) => item.msg).join(' ') : ''; }
  private scrollEnd(): void { const node = this.thread?.nativeElement; if (node) node.scrollTop = node.scrollHeight; }
}
