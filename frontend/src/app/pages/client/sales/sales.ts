import { CommonModule } from '@angular/common';
import { ChangeDetectorRef, Component, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { HttpClient } from '@angular/common/http';
import { API_V1_URL } from '../../../core/config/api.config';

const FALLBACK_TIMEZONES = [
  'UTC', 'America/Lima', 'America/Bogota', 'America/Guayaquil', 'America/Mexico_City',
  'America/New_York', 'America/Chicago', 'America/Denver', 'America/Los_Angeles',
  'America/Toronto', 'America/Vancouver', 'America/Santiago', 'America/Argentina/Buenos_Aires',
  'America/Sao_Paulo', 'Europe/London', 'Europe/Madrid', 'Europe/Paris', 'Asia/Dubai', 'Asia/Tokyo',
];

@Component({
  selector: 'app-sales', standalone: true, imports: [CommonModule, FormsModule],
  templateUrl: './sales.html', styleUrls: ['./sales.scss', './sales-visit.scss'],
})
export class SalesComponent implements OnInit {
  meetings: any[] = []; availability: any[] = []; salesUsers: any[] = [];
  salesUserId = ''; loading = true; saving = false; availabilitySaving = false; attachmentSaving = false;
  selected: any = null; selectedLead: any = null; leadLoading = false; selectedDay: Date | null = null;
  month = new Date(new Date().getFullYear(), new Date().getMonth(), 1);
  error = ''; success = ''; role = typeof localStorage === 'undefined' ? '' : localStorage.getItem('bp_role') || '';
  readonly timezones = this.loadTimezones();
  timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'; blockStart = '09:00'; blockEnd = '17:00';
  settingsOpen = false; calendarProvider = 'google'; calendarId = ''; calendarStatus = 'not_connected'; calendarSaving = false;
  closingDate = ''; visitPhoto: File | null = null; saleEvidence: File | null = null; chatOpen = false;
  persistedStatus = '';

  constructor(private http: HttpClient, private cdr: ChangeDetectorRef) {}

  ngOnInit(): void {
    if (this.role === 'sales') { this.loadSalesSchedule(); this.loadCalendarConnection(); return; }
    this.loadManagerSchedule();
  }

  get monthRange(): { start: string; end: string } {
    return {
      start: new Date(this.month.getFullYear(), this.month.getMonth(), 1).toISOString(),
      end: new Date(this.month.getFullYear(), this.month.getMonth() + 1, 1).toISOString(),
    };
  }

  loadSalesSchedule(): void {
    this.loading = true; this.error = '';
    const range = this.monthRange;
    this.http.get<any>(`${API_V1_URL}/sales/schedule/me?start=${encodeURIComponent(range.start)}&end=${encodeURIComponent(range.end)}`).subscribe({
      next: data => { this.meetings = data.meetings || []; this.availability = data.availability || []; this.loading = false; this.cdr.markForCheck(); },
      error: err => this.fail(err.error?.detail || 'Your schedule could not be loaded.'),
    });
  }

  loadManagerSchedule(): void {
    this.loading = true; this.error = '';
    const range = this.monthRange; const filter = this.salesUserId ? `&sales_user_id=${encodeURIComponent(this.salesUserId)}` : '';
    this.http.get<any>(`${API_V1_URL}/sales/schedule?start=${encodeURIComponent(range.start)}&end=${encodeURIComponent(range.end)}${filter}`).subscribe({
      next: data => {
        this.meetings = data.meetings || []; this.availability = data.availability || [];
        this.salesUsers = data.sales_users || this.salesUsers; this.loading = false; this.cdr.markForCheck();
      },
      error: err => this.fail(err.error?.detail || 'Company schedule could not be loaded.'),
    });
  }

  loadCalendarConnection(): void {
    this.http.get<any[]>(`${API_V1_URL}/sales/calendar-connections/me`).subscribe({ next: rows => {
      const item = rows[0]; if (item) { this.calendarProvider = item.provider; this.calendarId = item.calendar_id || ''; this.calendarStatus = item.status; }
      this.cdr.markForCheck();
    }});
  }

  addAvailability(): void {
    if (!this.selectedDay || this.availabilitySaving || this.blockEnd <= this.blockStart) return;
    const startsAt = this.wallTimeToUtc(this.selectedDay, this.blockStart, this.timezone);
    const endsAt = this.wallTimeToUtc(this.selectedDay, this.blockEnd, this.timezone);
    this.availabilitySaving = true;
    this.http.post<any>(`${API_V1_URL}/sales/availability-blocks/me`, {
      starts_at: startsAt.toISOString(), ends_at: endsAt.toISOString(), timezone: this.timezone,
    }).subscribe({
      next: () => { this.availabilitySaving = false; this.success = 'Availability block added.'; this.loadSalesSchedule(); },
      error: err => { this.availabilitySaving = false; this.error = err.error?.detail || 'Availability could not be added.'; this.cdr.markForCheck(); },
    });
  }

  removeAvailability(block: any): void {
    this.http.delete(`${API_V1_URL}/sales/availability-blocks/me/${block.id}`).subscribe({
      next: () => { this.success = 'Availability block removed.'; this.loadSalesSchedule(); },
      error: err => { this.error = err.error?.detail || 'Availability could not be removed.'; this.cdr.markForCheck(); },
    });
  }

  selectMeeting(meeting: any): void {
    this.selected = meeting; this.selectedDay = null; this.selectedLead = null; this.chatOpen = false;
    this.persistedStatus = meeting.status;
    this.closingDate = meeting.sale_closed_at ? String(meeting.sale_closed_at).slice(0, 10) : '';
    if (!meeting.lead_id) return;
    this.leadLoading = true;
    this.http.get<any>(`${API_V1_URL}/sales/leads/${meeting.lead_id}`).subscribe({
      next: lead => { this.selectedLead = lead; this.leadLoading = false; this.cdr.markForCheck(); },
      error: err => { this.leadLoading = false; this.error = err.error?.detail || 'Lead detail could not be loaded.'; this.cdr.markForCheck(); },
    });
  }

  selectDay(day: Date): void {
    if (this.role !== 'sales' || day.getMonth() !== this.month.getMonth()) return;
    this.selectedDay = day; this.selected = null; this.selectedLead = null;
  }

  saveCalendarConnection(): void {
    if (!this.calendarId.trim() || this.calendarSaving) return;
    this.calendarSaving = true;
    this.http.put<any>(`${API_V1_URL}/sales/calendar-connections/me`, { provider: this.calendarProvider, calendar_id: this.calendarId.trim() }).subscribe({
      next: row => { this.calendarSaving = false; this.calendarStatus = row.status; this.success = 'Calendar configuration saved.'; this.cdr.markForCheck(); },
      error: err => { this.calendarSaving = false; this.error = err.error?.detail || 'Calendar configuration could not be saved.'; this.cdr.markForCheck(); },
    });
  }

  saveMeeting(): void {
    if (!this.selected || this.role !== 'sales') return; this.saving = true;
    const payload: any = {
      status: this.selected.status, confirmation_status: this.selected.confirmation_status,
      visit_notes: this.selected.visit_notes || null, visit_details: this.selected.visit_details || null,
    };
    if (this.selected.status === 'sale_closed' && this.closingDate) payload.sale_closed_at = `${this.closingDate}T12:00:00`;
    this.http.put<any>(`${API_V1_URL}/sales/meetings/${this.selected.id}`, payload).subscribe({
      next: row => { Object.assign(this.selected, row); this.persistedStatus = row.status; this.saving = false; this.success = 'Appointment report updated.'; this.refreshMeeting(row); this.cdr.markForCheck(); },
      error: err => { this.saving = false; this.error = err.error?.detail || 'Appointment could not be updated.'; this.cdr.markForCheck(); },
    });
  }

  selectFile(event: Event, kind: 'visit_photo' | 'sale_evidence'): void {
    const file = (event.target as HTMLInputElement).files?.[0] || null;
    if (kind === 'visit_photo') this.visitPhoto = file; else this.saleEvidence = file;
  }

  uploadAttachment(kind: 'visit_photo' | 'sale_evidence'): void {
    const file = kind === 'visit_photo' ? this.visitPhoto : this.saleEvidence;
    if (!this.selected || !file || this.attachmentSaving) return;
    const body = new FormData(); body.append('kind', kind); body.append('file', file);
    this.attachmentSaving = true;
    this.http.post<any>(`${API_V1_URL}/sales/meetings/${this.selected.id}/attachments`, body).subscribe({
      next: attachment => {
        this.selected.attachments = [...(this.selected.attachments || []), attachment]; this.attachmentSaving = false;
        if (kind === 'visit_photo') this.visitPhoto = null; else this.saleEvidence = null;
        this.success = kind === 'visit_photo' ? 'Visit photo uploaded.' : 'Sale evidence uploaded.'; this.cdr.markForCheck();
      },
      error: err => { this.attachmentSaving = false; this.error = err.error?.detail || 'Attachment could not be uploaded.'; this.cdr.markForCheck(); },
    });
  }

  downloadAttachment(attachment: any): void {
    this.http.get(`${API_V1_URL}/sales/meetings/${this.selected.id}/attachments/${attachment.id}`, { responseType: 'blob' }).subscribe({
      next: blob => { const url = URL.createObjectURL(blob); const anchor = document.createElement('a'); anchor.href = url; anchor.download = attachment.original_filename; anchor.click(); URL.revokeObjectURL(url); },
      error: () => { this.error = 'Attachment could not be downloaded.'; this.cdr.markForCheck(); },
    });
  }

  statusOptions(status: string): { value: string; label: string }[] {
    status = this.persistedStatus || status;
    const current = [{ value: status, label: this.statusLabel(status) }];
    const next: Record<string, string[]> = {
      scheduled: ['confirmed', 'in_progress', 'cancelled', 'no_show'], confirmed: ['in_progress', 'cancelled', 'no_show'],
      in_progress: ['completed_sale_pending', 'sale_closed'], completed_sale_pending: ['sale_closed'],
    };
    return [...current, ...(next[status] || []).map(value => ({ value, label: this.statusLabel(value) }))];
  }

  statusLabel(status: string): string {
    return ({ scheduled: 'Scheduled', confirmed: 'Confirmed', in_progress: 'Visit in progress', completed: 'Completed',
      completed_sale_pending: 'Completed · sale pending', sale_closed: 'Sale completed', cancelled: 'Cancelled', no_show: 'No show' } as any)[status] || status;
  }

  get days(): Date[] { const start = new Date(this.month.getFullYear(), this.month.getMonth(), 1); const grid = new Date(start); grid.setDate(1 - start.getDay()); return Array.from({ length: 42 }, (_, i) => new Date(grid.getFullYear(), grid.getMonth(), grid.getDate() + i)); }
  meetingsFor(day: Date): any[] { return this.meetings.filter(item => new Date(item.meeting_time).toDateString() === day.toDateString()); }
  availabilityFor(day: Date): any[] { return this.availability.filter(item => this.dateKey(item.starts_at, item.timezone) === this.localDateKey(day)); }
  formatBlockTime(value: string, timezone: string): string { return new Intl.DateTimeFormat('en-US', { hour: 'numeric', minute: '2-digit', timeZone: timezone || 'UTC' }).format(this.utcDate(value)); }
  utcDate(value: string): Date { return new Date(/[zZ]|[+-]\d\d:\d\d$/.test(value) ? value : `${value}Z`); }
  move(delta: number): void { this.month = new Date(this.month.getFullYear(), this.month.getMonth() + delta, 1); this.selectedDay = null; this.selected = null; this.role === 'sales' ? this.loadSalesSchedule() : this.loadManagerSchedule(); }
  count(status: string): number { return this.meetings.filter(item => item.status === status).length; }
  trackById(_: number, item: any): string { return item.id; }
  objectEntries(value: any): { key: string; value: any }[] { return Object.entries(value || {}).map(([key, item]) => ({ key, value: item && typeof item === 'object' ? JSON.stringify(item) : item })); }
  hasEvidence(): boolean { return (this.selected?.attachments || []).some((item: any) => item.kind === 'sale_evidence'); }

  private refreshMeeting(row: any): void { const index = this.meetings.findIndex(item => item.id === row.id); if (index >= 0) this.meetings[index] = row; }
  private localDateKey(date: Date): string { return `${date.getFullYear()}-${date.getMonth() + 1}-${date.getDate()}`; }
  private dateKey(value: string, timezone: string): string {
    const parts = new Intl.DateTimeFormat('en-US', { timeZone: timezone || 'UTC', year: 'numeric', month: 'numeric', day: 'numeric' }).formatToParts(this.utcDate(value));
    const read = (type: string) => Number(parts.find(item => item.type === type)?.value || 0);
    return `${read('year')}-${read('month')}-${read('day')}`;
  }
  private wallTimeToUtc(day: Date, time: string, timezone: string): Date {
    const [hour, minute] = time.split(':').map(Number); const wanted = Date.UTC(day.getFullYear(), day.getMonth(), day.getDate(), hour, minute);
    let guess = wanted;
    for (let index = 0; index < 2; index++) {
      const parts = new Intl.DateTimeFormat('en-US', { timeZone: timezone, year: 'numeric', month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).formatToParts(new Date(guess));
      const read = (type: string) => Number(parts.find(item => item.type === type)?.value || 0);
      const represented = Date.UTC(read('year'), read('month') - 1, read('day'), read('hour'), read('minute'));
      guess += wanted - represented;
    }
    return new Date(guess);
  }
  private loadTimezones(): string[] {
    const supported = (Intl as any).supportedValuesOf?.('timeZone') as string[] | undefined;
    return Array.from(new Set([...(supported || FALLBACK_TIMEZONES), 'UTC'])).sort();
  }
  private fail(message: string): void { this.loading = false; this.error = message; this.cdr.markForCheck(); }
}
