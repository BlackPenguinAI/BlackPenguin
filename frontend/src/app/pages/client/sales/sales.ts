import { CommonModule } from '@angular/common';
import { ChangeDetectorRef, Component, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { HttpClient } from '@angular/common/http';

import { API_V1_URL } from '../../../core/config/api.config';
import { canonicalTimezone, filterTimezoneOptions, supportedTimezones, timezoneLabel } from '../../../core/timezones';

type ScheduleSection = 'availability' | 'appointments';
type CalendarView = 'month' | 'week' | 'day';

@Component({
  selector: 'app-sales', standalone: true, imports: [CommonModule, FormsModule],
  templateUrl: './sales.html', styleUrls: ['./sales.scss', './sales-visit.scss'],
})
export class SalesComponent implements OnInit {
  meetings: any[] = []; availability: any[] = []; salesUsers: any[] = []; projects: any[] = []; leads: any[] = [];
  role = typeof localStorage === 'undefined' ? '' : localStorage.getItem('bp_role') || '';
  section: ScheduleSection = 'availability'; view: CalendarView = 'month'; cursor = new Date();
  salesUserId = ''; projectId = ''; userTimezone = 'UTC'; timezone = 'UTC';
  readonly timezones = supportedTimezones(); timezoneSearch = ''; readonly timezoneLabel = timezoneLabel;
  get filteredTimezoneOptions() { return filterTimezoneOptions(this.timezoneSearch); }
  loading = true; saving = false; availabilitySaving = false; attachmentSaving = false; projectTimezoneSaving = false;
  error = ''; success = ''; selected: any = null; selectedLead: any = null; selectedDay: Date | null = null; editingBlock: any = null;
  leadLoading = false; chatOpen = false; persistedStatus = ''; blockStart = '09:00'; blockEnd = '17:00'; closingDate = '';
  visitPhoto: File | null = null; saleEvidence: File | null = null; managerMeetingTime = ''; calendarStatus = 'not_connected';
  newAppointment = { lead_id: '', time: '10:00', duration_minutes: 45, modality: 'in_person', notes: '' };

  constructor(private http: HttpClient, private cdr: ChangeDetectorRef) {}

  ngOnInit(): void { this.loadProfile(); this.loadProjects(); this.reload(); if (this.role === 'sales') this.loadCalendarConnection(); }
  get isManager(): boolean { return this.role === 'admin' || this.role === 'assistant'; }
  get selectedProject(): any { return this.projects.find(project => project.id === this.projectId); }

  get range(): { start: string; end: string } {
    let start: Date; let end: Date;
    if (this.view === 'month') { start = new Date(this.cursor.getFullYear(), this.cursor.getMonth(), 1); end = new Date(this.cursor.getFullYear(), this.cursor.getMonth() + 1, 1); }
    else if (this.view === 'week') { start = this.startOfDay(this.cursor); start.setDate(start.getDate() - start.getDay()); end = new Date(start); end.setDate(end.getDate() + 7); }
    else { start = this.startOfDay(this.cursor); end = new Date(start); end.setDate(end.getDate() + 1); }
    return { start: start.toISOString(), end: end.toISOString() };
  }

  get days(): Date[] {
    if (this.view === 'day') return [this.startOfDay(this.cursor)];
    if (this.view === 'week') { const start = this.startOfDay(this.cursor); start.setDate(start.getDate() - start.getDay()); return Array.from({ length: 7 }, (_, index) => new Date(start.getFullYear(), start.getMonth(), start.getDate() + index)); }
    const first = new Date(this.cursor.getFullYear(), this.cursor.getMonth(), 1); const grid = new Date(first); grid.setDate(1 - first.getDay());
    return Array.from({ length: 42 }, (_, index) => new Date(grid.getFullYear(), grid.getMonth(), grid.getDate() + index));
  }

  get calendarTitle(): string {
    if (this.view === 'day') return new Intl.DateTimeFormat('en-US', { dateStyle: 'full' }).format(this.cursor);
    if (this.view === 'week') { const days = this.days; return `${new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric' }).format(days[0])} – ${new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric', year: 'numeric' }).format(days[6])}`; }
    return new Intl.DateTimeFormat('en-US', { month: 'long', year: 'numeric' }).format(this.cursor);
  }

  setSection(section: ScheduleSection): void { this.section = section; this.selected = null; this.selectedDay = null; this.editingBlock = null; }
  setView(view: CalendarView): void { this.view = view; this.selected = null; this.selectedDay = null; this.reload(); }
  reload(): void { this.role === 'sales' ? this.loadSalesSchedule() : this.loadManagerSchedule(); }

  loadSalesSchedule(): void {
    this.loading = true; this.error = ''; const range = this.range; const projectFilter = this.projectId ? `&project_id=${encodeURIComponent(this.projectId)}` : '';
    this.http.get<any>(`${API_V1_URL}/sales/schedule/me?start=${encodeURIComponent(range.start)}&end=${encodeURIComponent(range.end)}${projectFilter}`).subscribe({ next: data => this.acceptSchedule(data), error: err => this.fail(err.error?.detail || 'Your schedule could not be loaded.') });
  }

  loadManagerSchedule(): void {
    this.loading = true; this.error = ''; const range = this.range;
    const userFilter = this.salesUserId ? `&sales_user_id=${encodeURIComponent(this.salesUserId)}` : '';
    const projectFilter = this.projectId ? `&project_id=${encodeURIComponent(this.projectId)}` : '';
    this.http.get<any>(`${API_V1_URL}/sales/schedule?start=${encodeURIComponent(range.start)}&end=${encodeURIComponent(range.end)}${userFilter}${projectFilter}`).subscribe({
      next: data => { this.salesUsers = data.sales_users || this.salesUsers; this.acceptSchedule(data); },
      error: err => this.fail(err.error?.detail || 'Company schedule could not be loaded.'),
    });
  }

  filtersChanged(): void {
    this.timezone = canonicalTimezone(this.selectedProject?.timezone || this.userTimezone); this.selected = null; this.selectedDay = null; this.editingBlock = null;
    if (this.isManager && this.projectId) this.loadLeads(); else this.leads = [];
    this.reload();
  }

  selectDay(day: Date): void {
    if (this.view === 'month' && day.getMonth() !== this.cursor.getMonth()) return;
    this.selectedDay = day; this.selected = null; this.selectedLead = null; this.editingBlock = null; this.blockStart = '09:00'; this.blockEnd = '17:00';
  }

  saveAvailability(): void {
    if (!this.selectedDay || this.availabilitySaving || this.blockEnd <= this.blockStart) return;
    const target = this.role === 'sales' ? 'me' : this.salesUserId;
    if (!target) { this.error = 'Select a Sales user before managing availability.'; return; }
    const body = { starts_at: this.wallTimeToUtc(this.selectedDay, this.blockStart, this.timezone).toISOString(), ends_at: this.wallTimeToUtc(this.selectedDay, this.blockEnd, this.timezone).toISOString(), timezone: this.timezone };
    const base = `${API_V1_URL}/sales/availability-blocks/${target}`;
    const request = this.editingBlock ? this.http.put(`${base}/${this.editingBlock.id}`, body) : this.http.post(base, body);
    this.availabilitySaving = true;
    request.subscribe({
      next: () => { this.availabilitySaving = false; this.success = this.editingBlock ? 'Availability block updated.' : 'Availability block added.'; this.editingBlock = null; this.reload(); },
      error: err => { this.availabilitySaving = false; this.error = err.error?.detail || 'Availability could not be saved.'; this.cdr.markForCheck(); },
    });
  }

  editAvailability(block: any): void { if (!this.canManageBlock(block)) return; this.editingBlock = block; this.timezone = canonicalTimezone(block.timezone || this.timezone); this.blockStart = this.timeValue(block.starts_at, block.timezone || this.timezone); this.blockEnd = this.timeValue(block.ends_at, block.timezone || this.timezone); }
  cancelBlockEdit(): void { this.editingBlock = null; this.blockStart = '09:00'; this.blockEnd = '17:00'; }
  removeAvailability(block: any): void {
    if (!this.canManageBlock(block)) return; const target = this.role === 'sales' ? 'me' : block.user_id;
    this.http.delete(`${API_V1_URL}/sales/availability-blocks/${target}/${block.id}`).subscribe({ next: () => { this.success = 'Availability block removed.'; this.reload(); }, error: err => { this.error = err.error?.detail || 'Availability could not be removed.'; this.cdr.markForCheck(); } });
  }
  canManageBlock(block: any): boolean { return this.role === 'sales' || (!!this.salesUserId && this.salesUserId === block.user_id); }

  createAppointment(): void {
    if (!this.isManager || !this.selectedDay || !this.projectId || !this.salesUserId || !this.newAppointment.lead_id || this.saving) return;
    this.saving = true;
    this.http.post<any>(`${API_V1_URL}/sales/meetings`, {
      project_id: this.projectId, lead_id: this.newAppointment.lead_id, broker_id: null, assigned_sales_user_id: this.salesUserId,
      meeting_time: this.wallTimeToUtc(this.selectedDay, this.newAppointment.time, this.timezone).toISOString(), duration_minutes: Number(this.newAppointment.duration_minutes),
      modality: this.newAppointment.modality, notes: this.newAppointment.notes || null,
    }).subscribe({
      next: () => { this.saving = false; this.success = 'Appointment created and assigned.'; this.newAppointment = { lead_id: '', time: '10:00', duration_minutes: 45, modality: 'in_person', notes: '' }; this.reload(); },
      error: err => { this.saving = false; this.error = err.error?.detail || 'Appointment could not be created.'; this.cdr.markForCheck(); },
    });
  }

  selectMeeting(meeting: any): void {
    this.selected = { ...meeting }; this.selectedDay = null; this.selectedLead = null; this.chatOpen = false; this.persistedStatus = meeting.status;
    this.closingDate = meeting.sale_closed_at ? String(meeting.sale_closed_at).slice(0, 10) : '';
    this.managerMeetingTime = this.datetimeLocalValue(meeting.meeting_time, meeting.project_timezone || this.timezone);
    if (!meeting.lead_id) return; this.leadLoading = true;
    this.http.get<any>(`${API_V1_URL}/sales/leads/${meeting.lead_id}`).subscribe({ next: lead => { this.selectedLead = lead; this.leadLoading = false; this.cdr.markForCheck(); }, error: err => { this.leadLoading = false; this.error = err.error?.detail || 'Lead detail could not be loaded.'; this.cdr.markForCheck(); } });
  }

  saveManagerMeeting(): void {
    if (!this.isManager || !this.selected || !this.managerMeetingTime || this.saving) return;
    const [date, time] = this.managerMeetingTime.split('T'); const [year, month, day] = date.split('-').map(Number); const wallDay = new Date(year, month - 1, day); this.saving = true;
    this.http.put<any>(`${API_V1_URL}/sales/meetings/${this.selected.id}`, {
      assigned_sales_user_id: this.selected.assigned_sales_user_id,
      meeting_time: this.wallTimeToUtc(wallDay, time, this.selected.project_timezone || this.timezone).toISOString(),
      duration_minutes: Number(this.selected.duration_minutes), modality: this.selected.modality, status: this.selected.status,
      confirmation_status: this.selected.confirmation_status, notes: this.selected.notes || null,
    }).subscribe({ next: row => { this.saving = false; this.success = 'Appointment updated.'; this.selected = row; this.persistedStatus = row.status; this.reload(); }, error: err => { this.saving = false; this.error = err.error?.detail || 'Appointment could not be updated.'; this.cdr.markForCheck(); } });
  }

  deleteAppointment(): void {
    if (!this.isManager || !this.selected || this.saving) return; this.saving = true;
    this.http.delete(`${API_V1_URL}/sales/meetings/${this.selected.id}`).subscribe({ next: () => { this.saving = false; this.success = 'Appointment deleted.'; this.selected = null; this.reload(); }, error: err => { this.saving = false; this.error = err.error?.detail || 'Appointment could not be deleted.'; this.cdr.markForCheck(); } });
  }

  saveMeeting(): void {
    if (!this.selected || this.role !== 'sales') return; this.saving = true;
    const payload: any = { status: this.selected.status, confirmation_status: this.selected.confirmation_status, visit_notes: this.selected.visit_notes || null, visit_details: this.selected.visit_details || null };
    if (this.selected.status === 'sale_closed' && this.closingDate) payload.sale_closed_at = `${this.closingDate}T12:00:00`;
    this.http.put<any>(`${API_V1_URL}/sales/meetings/${this.selected.id}`, payload).subscribe({ next: row => { Object.assign(this.selected, row); this.persistedStatus = row.status; this.saving = false; this.success = 'Appointment report updated.'; this.refreshMeeting(row); this.cdr.markForCheck(); }, error: err => { this.saving = false; this.error = err.error?.detail || 'Appointment could not be updated.'; this.cdr.markForCheck(); } });
  }

  saveProjectTimezone(): void {
    if (!this.isManager || !this.projectId || this.projectTimezoneSaving) return; this.projectTimezoneSaving = true;
    this.http.patch<any>(`${API_V1_URL}/projects/${this.projectId}/timezone`, { timezone: this.timezone }).subscribe({ next: project => { const index = this.projects.findIndex(item => item.id === project.id); if (index >= 0) this.projects[index] = project; this.projectTimezoneSaving = false; this.success = 'Project timezone saved.'; this.cdr.markForCheck(); }, error: err => { this.projectTimezoneSaving = false; this.error = err.error?.detail || 'Project timezone could not be saved.'; this.cdr.markForCheck(); } });
  }

  selectFile(event: Event, kind: 'visit_photo' | 'sale_evidence'): void { const file = (event.target as HTMLInputElement).files?.[0] || null; if (kind === 'visit_photo') this.visitPhoto = file; else this.saleEvidence = file; }
  uploadAttachment(kind: 'visit_photo' | 'sale_evidence'): void {
    const file = kind === 'visit_photo' ? this.visitPhoto : this.saleEvidence; if (!this.selected || !file || this.attachmentSaving) return;
    const body = new FormData(); body.append('kind', kind); body.append('file', file); this.attachmentSaving = true;
    this.http.post<any>(`${API_V1_URL}/sales/meetings/${this.selected.id}/attachments`, body).subscribe({ next: attachment => { this.selected.attachments = [...(this.selected.attachments || []), attachment]; this.attachmentSaving = false; if (kind === 'visit_photo') this.visitPhoto = null; else this.saleEvidence = null; this.success = kind === 'visit_photo' ? 'Visit photo uploaded.' : 'Sale evidence uploaded.'; this.cdr.markForCheck(); }, error: err => { this.attachmentSaving = false; this.error = err.error?.detail || 'Attachment could not be uploaded.'; this.cdr.markForCheck(); } });
  }
  downloadAttachment(attachment: any): void { this.http.get(`${API_V1_URL}/sales/meetings/${this.selected.id}/attachments/${attachment.id}`, { responseType: 'blob' }).subscribe({ next: blob => { const url = URL.createObjectURL(blob); const anchor = document.createElement('a'); anchor.href = url; anchor.download = attachment.original_filename; anchor.click(); URL.revokeObjectURL(url); }, error: () => { this.error = 'Attachment could not be downloaded.'; this.cdr.markForCheck(); } }); }

  statusOptions(status: string): { value: string; label: string }[] {
    status = this.persistedStatus || status; const current = [{ value: status, label: this.statusLabel(status) }];
    const next: Record<string, string[]> = { scheduled: ['confirmed', 'in_progress', 'cancelled', 'no_show'], confirmed: ['in_progress', 'cancelled', 'no_show'], in_progress: ['completed', 'completed_sale_pending', 'sale_closed'], completed_sale_pending: ['sale_closed'] };
    return [...current, ...(next[status] || []).map(value => ({ value, label: this.statusLabel(value) }))];
  }
  statusLabel(status: string): string { return ({ scheduled: 'Scheduled', confirmed: 'Confirmed', in_progress: 'Visit in progress', completed: 'Completed', completed_sale_pending: 'Completed · sale pending', sale_closed: 'Sale completed', cancelled: 'Cancelled', no_show: 'No show' } as any)[status] || status; }
  meetingsFor(day: Date): any[] { return this.meetings.filter(item => this.dateKey(item.meeting_time, item.project_timezone || this.timezone) === this.localDateKey(day)); }
  availabilityFor(day: Date): any[] { return this.availability.filter(item => this.dateKey(item.starts_at, item.timezone) === this.localDateKey(day)); }
  formatBlockTime(value: string, timezone: string): string { return this.timeValue(value, timezone); }
  formatMeetingTime(meeting: any): string { return new Intl.DateTimeFormat('en-US', { dateStyle: 'medium', timeStyle: 'short', timeZone: meeting.project_timezone || this.timezone }).format(this.utcDate(meeting.meeting_time)); }
  utcDate(value: string): Date { return new Date(/[zZ]|[+-]\d\d:\d\d$/.test(value) ? value : `${value}Z`); }
  move(delta: number): void { const next = new Date(this.cursor); if (this.view === 'month') next.setMonth(next.getMonth() + delta); else next.setDate(next.getDate() + delta * (this.view === 'week' ? 7 : 1)); this.cursor = next; this.selectedDay = null; this.selected = null; this.reload(); }
  goToday(): void { this.cursor = new Date(); this.selectedDay = null; this.selected = null; this.reload(); }
  count(status: string): number { return this.meetings.filter(item => item.status === status).length; }
  trackById(_: number, item: any): string { return item.id; }
  objectEntries(value: any): { key: string; value: any }[] { return Object.entries(value || {}).map(([key, item]) => ({ key, value: item && typeof item === 'object' ? JSON.stringify(item) : item })); }
  hasEvidence(): boolean { return (this.selected?.attachments || []).some((item: any) => item.kind === 'sale_evidence'); }

  private acceptSchedule(data: any): void { this.meetings = data.meetings || []; this.availability = data.availability || []; this.loading = false; this.cdr.markForCheck(); }
  private loadProfile(): void { this.http.get<any>(`${API_V1_URL}/users/me`).subscribe({ next: profile => { this.userTimezone = canonicalTimezone(profile.timezone || 'UTC'); if (!this.projectId) this.timezone = this.userTimezone; this.cdr.markForCheck(); } }); }
  private loadProjects(): void { this.http.get<any[]>(`${API_V1_URL}/projects/`).subscribe({ next: rows => { this.projects = rows || []; this.cdr.markForCheck(); } }); }
  private loadLeads(): void { this.http.get<any[]>(`${API_V1_URL}/sales/projects/${this.projectId}/leads-report`).subscribe({ next: rows => { this.leads = rows || []; this.cdr.markForCheck(); }, error: () => { this.leads = []; this.cdr.markForCheck(); } }); }
  private loadCalendarConnection(): void { this.http.get<any[]>(`${API_V1_URL}/sales/calendar-connections/me`).subscribe({ next: rows => { this.calendarStatus = rows[0]?.status || 'not_connected'; this.cdr.markForCheck(); } }); }
  private refreshMeeting(row: any): void { const index = this.meetings.findIndex(item => item.id === row.id); if (index >= 0) this.meetings[index] = row; }
  private startOfDay(value: Date): Date { return new Date(value.getFullYear(), value.getMonth(), value.getDate()); }
  private localDateKey(date: Date): string { return `${date.getFullYear()}-${date.getMonth() + 1}-${date.getDate()}`; }
  private dateKey(value: string, timezone: string): string { const parts = new Intl.DateTimeFormat('en-US', { timeZone: timezone || 'UTC', year: 'numeric', month: 'numeric', day: 'numeric' }).formatToParts(this.utcDate(value)); const read = (type: string) => Number(parts.find(item => item.type === type)?.value || 0); return `${read('year')}-${read('month')}-${read('day')}`; }
  private timeValue(value: string, timezone: string): string { const parts = new Intl.DateTimeFormat('en-US', { timeZone: timezone || 'UTC', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).formatToParts(this.utcDate(value)); const read = (type: string) => parts.find(item => item.type === type)?.value || '00'; return `${read('hour')}:${read('minute')}`; }
  private datetimeLocalValue(value: string, timezone: string): string { const parts = new Intl.DateTimeFormat('en-US', { timeZone: timezone || 'UTC', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).formatToParts(this.utcDate(value)); const read = (type: string) => parts.find(item => item.type === type)?.value || '00'; return `${read('year')}-${read('month')}-${read('day')}T${read('hour')}:${read('minute')}`; }
  private wallTimeToUtc(day: Date, time: string, timezone: string): Date { const [hour, minute] = time.split(':').map(Number); const wanted = Date.UTC(day.getFullYear(), day.getMonth(), day.getDate(), hour, minute); let guess = wanted; for (let index = 0; index < 3; index++) { const parts = new Intl.DateTimeFormat('en-US', { timeZone: timezone, year: 'numeric', month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).formatToParts(new Date(guess)); const read = (type: string) => Number(parts.find(item => item.type === type)?.value || 0); const represented = Date.UTC(read('year'), read('month') - 1, read('day'), read('hour'), read('minute')); guess += wanted - represented; } return new Date(guess); }
  private fail(message: string): void { this.loading = false; this.error = message; this.cdr.markForCheck(); }
}
