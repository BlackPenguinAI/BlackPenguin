import { CommonModule } from '@angular/common';
import { ChangeDetectorRef, Component, ElementRef, OnInit, ViewChild } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { HttpClient } from '@angular/common/http';
import { ActivatedRoute } from '@angular/router';
import { finalize } from 'rxjs';
import { API_V1_URL } from '../../../core/config/api.config';

@Component({
  selector: 'app-agent',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './agent.html',
  styleUrls: ['./agent.scss'],
})
export class AgentComponent implements OnInit {
  role = typeof localStorage === 'undefined' ? '' : localStorage.getItem('bp_role') || '';
  @ViewChild('thread') thread?: ElementRef<HTMLElement>;
  options: any[] = [];
  conversations: any[] = [];
  messages: any[] = [];
  slots: any[] = [];
  projectId = '';
  campaignId = '';
  selected: any = null;
  selectedSlot = '';
  loading = true;
  loadingMessages = false;
  sending = false;
  creating = false;
  advancing = false;
  confirming = false;
  generatingInitial = false;
  setupOpen = true;
  search = '';
  filter = 'all';
  draft = '';
  error = '';
  success = '';
  initialGenerationError = '';
  form: {
    first_name: string;
    last_name: string;
    phone: string;
    email: string;
    product_id: string;
    budget_min: number | null;
    budget_max: number | null;
    consent: boolean;
  } = this.emptyForm();

  constructor(
    private http: HttpClient,
    private cdr: ChangeDetectorRef,
    private route: ActivatedRoute,
  ) {}

  ngOnInit(): void {
    if (this.role === 'sales') {
      this.setupOpen = false;
      this.loadConversations();
    } else {
      this.loadOptions();
    }
  }

  loadOptions(): void {
    this.loading = true;
    this.error = '';
    this.http.get<any[]>(`${API_V1_URL}/sales-agent/simulation-options`).subscribe({
      next: (rows) => {
        this.options = rows;
        const requested = this.route.snapshot.queryParamMap.get('project');
        this.projectId = rows.find((row) => row.id === requested)?.id || '';
        this.campaignId = this.campaigns[0]?.id || '';
        this.loadConversations();
      },
      error: (err) => {
        this.loading = false;
        this.error = err.error?.detail || 'Simulation projects could not be loaded.';
        this.cdr.markForCheck();
      },
    });
  }

  projectChanged(): void {
    const preserveSetup = this.setupOpen;
    this.campaignId = this.campaigns[0]?.id || '';
    this.form.product_id = '';
    this.form.budget_min = null;
    this.form.budget_max = null;
    this.selected = null;
    this.messages = [];
    this.slots = [];
    this.loadConversations(false, '', preserveSetup);
  }

  get campaigns(): any[] {
    return this.options.find((row) => row.id === this.projectId)?.campaigns || [];
  }
  get currentProject(): any {
    return this.options.find((row) => row.id === this.projectId);
  }
  get products(): any[] {
    return this.currentProject?.products || [];
  }
  get currentProduct(): any {
    return this.products.find((row) => row.id === this.form.product_id);
  }
  get emailValid(): boolean {
    return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(this.form.email.trim());
  }
  get budgetValid(): boolean {
    const minimum = Number(this.form.budget_min);
    const maximumValue = this.form.budget_max;
    const maximum =
      maximumValue === null || maximumValue === undefined || maximumValue === ('' as any)
        ? null
        : Number(maximumValue);
    return minimum > 0 && (maximum === null || (maximum > 0 && maximum >= minimum));
  }
  get formComplete(): boolean {
    return !!(
      this.projectId &&
      this.campaignId &&
      this.form.first_name.trim() &&
      this.form.last_name.trim() &&
      this.form.phone.trim() &&
      this.emailValid &&
      this.form.product_id &&
      this.budgetValid &&
      this.form.consent
    );
  }

  loadConversations(keep = false, preferredConversationId = '', preserveSetup = false): void {
    this.loading = true;
    this.error = '';
    const url = this.projectId
      ? `${API_V1_URL}/sales-agent/conversations?project_id=${encodeURIComponent(this.projectId)}`
      : `${API_V1_URL}/sales-agent/conversations`;
    this.http
      .get<any[]>(url)
      .subscribe({
        next: (rows) => {
          this.conversations = rows;
          const requestedLead = this.route.snapshot.queryParamMap.get('lead');
          const next =
            rows.find((row) => row.id === preferredConversationId) ||
            (keep ? rows.find((row) => row.id === this.selected?.id) : null) ||
            rows.find((row) => row.lead_id === requestedLead) ||
            rows[0];
          this.loading = false;
          if (next && !preserveSetup) this.select(next);
          else {
            this.selected = next || null;
            this.setupOpen = preserveSetup || !next;
          }
          this.cdr.markForCheck();
        },
        error: (err) => {
          this.loading = false;
          this.error = err.error?.detail || 'Conversations could not be loaded.';
          this.cdr.markForCheck();
        },
      });
  }

  startSimulation(): void {
    if (!this.formComplete || this.creating) return;
    this.creating = true;
    this.error = '';
    this.success = '';
    this.http
      .post<any>(`${API_V1_URL}/sales-agent/simulations`, {
        project_id: this.projectId,
        campaign_id: this.campaignId,
        lead: {
          first_name: this.form.first_name.trim(),
          last_name: this.form.last_name.trim(),
          phone: this.form.phone.trim(),
          email: this.form.email.trim(),
          product_id: this.form.product_id,
          budget_min: Number(this.form.budget_min),
          budget_max:
            this.form.budget_max === null || this.form.budget_max === undefined
              ? null
              : Number(this.form.budget_max),
          consent: this.form.consent,
          custom_answers: {},
        },
      })
      .pipe(
        finalize(() => {
          this.creating = false;
          this.cdr.markForCheck();
        }),
      )
      .subscribe({
        next: (result) => {
          this.setupOpen = false;
          this.success = 'Lead created. The AI sales agent is preparing the first SMS.';
          this.resetForm();
          this.loadConversations(false, result.conversation_id);
        },
        error: (err) => {
          this.error =
            err.error?.detail ||
            this.validationMessage(err.error) ||
            'The simulation could not be created.';
          this.cdr.markForCheck();
        },
      });
  }

  select(conversation: any): void {
    const changed = this.selected?.id !== conversation.id;
    this.selected = conversation;
    this.setupOpen = false;
    if (changed) {
      this.messages = [];
      this.slots = [];
      this.selectedSlot = '';
      this.initialGenerationError = '';
    }
    this.error = '';
    this.refreshMessages(true);
    if (conversation.simulation_id && !conversation.appointment_id) this.loadSlots();
    if (
      conversation.simulation_id &&
      ['initializing', 'needs_retry', 'generating'].includes(conversation.simulation_status) &&
      !this.generatingInitial
    ) {
      this.generateInitial(conversation.simulation_id, conversation.id);
    }
  }

  refreshMessages(forceBottom = false): void {
    if (!this.selected?.id) return;
    const conversationId = this.selected.id;
    const stayAtBottom = forceBottom || this.isNearBottom();
    this.loadingMessages = true;
    this.http
      .get<any[]>(`${API_V1_URL}/sales-agent/conversations/${conversationId}/messages`)
      .subscribe({
        next: (rows) => {
          if (this.selected?.id !== conversationId) return;
          // API order is chronological. Keep an explicit stable client order as
          // a safeguard against cached/proxy responses with equal timestamps.
          this.messages = [...rows].sort((a, b) => {
            const byTime = new Date(a.created_at).getTime() - new Date(b.created_at).getTime();
            const byDirection = (a.direction === 'inbound' ? 0 : 1) - (b.direction === 'inbound' ? 0 : 1);
            return byTime || byDirection || String(a.id).localeCompare(String(b.id));
          });
          this.loadingMessages = false;
          this.cdr.markForCheck();
          if (stayAtBottom) setTimeout(() => this.scrollEnd());
        },
        error: () => {
          this.loadingMessages = false;
          this.error = 'The conversation could not be loaded.';
          this.cdr.markForCheck();
        },
      });
  }

  generateInitial(
    simulationId = this.selected?.simulation_id,
    conversationId = this.selected?.id,
  ): void {
    if (!simulationId || this.generatingInitial) return;
    this.generatingInitial = true;
    this.initialGenerationError = '';
    this.http
      .post<any>(`${API_V1_URL}/sales-agent/simulations/${simulationId}/initial-message`, {})
      .pipe(
        finalize(() => {
          this.generatingInitial = false;
          this.cdr.markForCheck();
        }),
      )
      .subscribe({
        next: () => {
          this.success = 'The first SMS is ready.';
          if (this.selected?.id === conversationId) this.refreshMessages(true);
          this.refreshConversationSummaries();
        },
        error: (err) => {
          this.initialGenerationError =
            err.status === 409
              ? 'The first SMS is still being generated. You can refresh the conversation or retry shortly.'
              : err.error?.detail ||
                'The first SMS could not be generated. The lead was saved and you can retry safely.';
          this.refreshConversationSummaries();
        },
      });
  }

  send(): void {
    const message = this.draft.trim();
    if (!message || !this.selected || this.sending) return;
    if (this.selected.channel === 'sms') {
      this.sendManual(message);
      return;
    }
    if (this.selected.is_paused) return;
    this.sending = true;
    this.error = '';
    this.http
      .post(`${API_V1_URL}/sales-agent/simulate`, { lead_id: this.selected.lead_id, message })
      .pipe(
        finalize(() => {
          this.sending = false;
          this.cdr.markForCheck();
        }),
      )
      .subscribe({
        next: () => {
          this.draft = '';
          this.refreshMessages(true);
          this.refreshConversationSummaries();
        },
        error: (err) => {
          this.error = err.error?.detail || 'The simulated turn could not be completed.';
          this.cdr.markForCheck();
        },
      });
  }

  onComposerKeydown(event: KeyboardEvent): void {
    if (event.key !== 'Enter' || event.shiftKey || event.isComposing) return;
    event.preventDefault();
    this.send();
  }

  private sendManual(message: string): void {
    if (!this.selected?.is_paused) {
      this.error = 'Pause the AI before sending a manual SMS.';
      return;
    }
    this.sending = true; this.error = '';
    this.http.post(`${API_V1_URL}/sales-agent/conversations/${this.selected.id}/manual-message`, { content: message })
      .pipe(finalize(() => { this.sending = false; this.cdr.markForCheck(); }))
      .subscribe({
        next: () => { this.draft = ''; this.refreshMessages(true); this.refreshConversationSummaries(); },
        error: err => { this.error = err.error?.detail || 'The manual SMS could not be sent.'; },
      });
  }

  get isLive(): boolean { return this.selected?.channel === 'sms'; }
  get canManualControl(): boolean { return this.role === 'admin' || this.role === 'assistant'; }

  refreshConversationSummaries(): void {
    const url = this.projectId
      ? `${API_V1_URL}/sales-agent/conversations?project_id=${encodeURIComponent(this.projectId)}`
      : `${API_V1_URL}/sales-agent/conversations`;
    this.http
      .get<any[]>(url)
      .subscribe({
        next: (rows) => {
          this.conversations = rows;
          const current = rows.find((row) => row.id === this.selected?.id);
          if (current) this.selected = current;
          this.cdr.markForCheck();
        },
      });
  }

  loadSlots(): void {
    if (!this.selected?.simulation_id) return;
    this.http
      .get<any[]>(`${API_V1_URL}/sales-agent/simulations/${this.selected.simulation_id}/slots`)
      .subscribe({
        next: (rows) => {
          this.slots = rows;
          if (!rows.find((row) => row.start_at === this.selectedSlot)) this.selectedSlot = '';
          this.cdr.markForCheck();
        },
        error: (err) => {
          this.slots = [];
          this.error = err.error?.detail || 'Available appointment times could not be loaded.';
          this.cdr.markForCheck();
        },
      });
  }

  confirmSlot(): void {
    if (!this.selected?.simulation_id || !this.selectedSlot || this.confirming) return;
    this.confirming = true;
    this.error = '';
    this.http
      .post<any>(
        `${API_V1_URL}/sales-agent/simulations/${this.selected.simulation_id}/appointments`,
        {
          start_at: this.selectedSlot,
          duration_minutes: 45,
          modality: 'virtual',
        },
      )
      .subscribe({
        next: (result) => {
          this.confirming = false;
          this.success = `Appointment assigned to ${result.assigned_sales_name}.`;
          this.loadConversations(true);
        },
        error: (err) => {
          this.confirming = false;
          this.error = err.error?.detail || 'The appointment could not be confirmed.';
          this.loadSlots();
        },
      });
  }

  advance(hours: number): void {
    if (!this.selected?.simulation_id || this.advancing) return;
    this.advancing = true;
    this.error = '';
    this.http
      .post<any>(`${API_V1_URL}/sales-agent/simulations/${this.selected.simulation_id}/advance`, {
        hours,
      })
      .subscribe({
        next: (result) => {
          this.advancing = false;
          this.success = result.processed_follow_ups
            ? `${result.processed_follow_ups} scheduled follow-up was generated.`
            : 'Virtual time advanced. No follow-up was due.';
          this.loadConversations(true);
        },
        error: (err) => {
          this.advancing = false;
          this.error = err.error?.detail || 'Virtual time could not be advanced.';
          this.cdr.markForCheck();
        },
      });
  }

  isReminder(message: any): boolean { return String(message.status || '').startsWith('simulated_follow_up_'); }

  reminderLabel(message: any): string {
    const hours = String(message.status || '').match(/_(24|48)h$/)?.[1];
    return hours ? `Reminder scheduled to arrive after +${hours}h` : 'Scheduled reminder';
  }

  approve(status: 'approved' | 'changes_requested'): void {
    if (!this.selected?.simulation_id) return;
    this.http
      .put(`${API_V1_URL}/sales-agent/simulations/${this.selected.simulation_id}/approval`, {
        status,
        notes: null,
      })
      .subscribe({
        next: () => {
          this.success =
            status === 'approved'
              ? 'This protocol test was approved.'
              : 'Changes were requested for this protocol test.';
          this.loadConversations(true);
        },
        error: (err) => {
          this.error = err.error?.detail || 'The review could not be saved.';
          this.cdr.markForCheck();
        },
      });
  }

  action(action: 'pause' | 'resume' | 'human_handoff'): void {
    if (!this.selected) return;
    this.http
      .post<any>(`${API_V1_URL}/sales-agent/conversations/${this.selected.id}/action`, { action })
      .subscribe({
        next: (row) => {
          this.selected = row;
          this.loadConversations(true);
        },
        error: (err) => {
          this.error = err.error?.detail || 'The action could not be saved.';
          this.cdr.markForCheck();
        },
      });
  }

  get visible(): any[] {
    const term = this.search.trim().toLowerCase();
    return this.conversations.filter(
      (row) =>
        (this.filter === 'all' || (this.filter === 'active' ? !row.is_paused : row.is_paused)) &&
        (!term || `${row.lead_name} ${row.phone} ${row.last_message}`.toLowerCase().includes(term)),
    );
  }
  initials(name: string): string {
    return name
      .split(/\s+/)
      .slice(0, 2)
      .map((value) => value[0])
      .join('')
      .toUpperCase();
  }
  formatMoney(value: number | null | undefined, currency: string | null | undefined): string {
    if (value === null || value === undefined) return 'Not provided';
    try {
      return new Intl.NumberFormat('en-US', {
        style: 'currency',
        currency: currency || 'USD',
        maximumFractionDigits: 0,
      }).format(value);
    } catch {
      return `${currency || ''} ${Number(value).toLocaleString()}`.trim();
    }
  }
  private emptyForm() {
    return {
      first_name: '',
      last_name: '',
      phone: '',
      email: '',
      product_id: '',
      budget_min: null,
      budget_max: null,
      consent: false,
    };
  }
  private resetForm(): void {
    this.form = this.emptyForm();
  }
  private validationMessage(error: any): string {
    return Array.isArray(error?.detail) ? error.detail.map((item: any) => item.msg).join(' ') : '';
  }
  private isNearBottom(): boolean {
    const node = this.thread?.nativeElement;
    return !node || node.scrollHeight - node.scrollTop - node.clientHeight < 100;
  }
  private scrollEnd(): void {
    const node = this.thread?.nativeElement;
    if (node) node.scrollTop = node.scrollHeight;
  }
}
