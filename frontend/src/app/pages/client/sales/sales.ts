import { CommonModule } from '@angular/common';
import { ChangeDetectorRef, Component, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { HttpClient } from '@angular/common/http';
import { RouterModule } from '@angular/router';
import { forkJoin } from 'rxjs';
import { API_V1_URL } from '../../../core/config/api.config';

@Component({
  selector: 'app-sales', standalone: true, imports: [CommonModule, FormsModule, RouterModule],
  templateUrl: './sales.html', styleUrls: ['./sales.scss'],
})
export class SalesComponent implements OnInit {
  projects: any[] = []; meetings: any[] = []; availability: any[] = []; leads: any[] = []; brokers: any[] = [];
  projectId = ''; loading = true; saving = false; availabilitySaving = false;
  selected: any = null; selectedLead: any = null; leadLoading = false; selectedDay: Date | null = null;
  month = new Date(new Date().getFullYear(), new Date().getMonth(), 1);
  error = ''; success = ''; role = typeof localStorage === 'undefined' ? '' : localStorage.getItem('bp_role') || '';
  timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'; blockStart = '09:00'; blockEnd = '17:00';
  settingsOpen = false; calendarProvider = 'google'; calendarId = ''; calendarStatus = 'not_connected'; calendarSaving = false;

  constructor(private http: HttpClient, private cdr: ChangeDetectorRef) {}

  ngOnInit(): void {
    if (this.role === 'sales') { this.loadSalesSchedule(); this.loadCalendarConnection(); return; }
    this.http.get<any[]>(`${API_V1_URL}/projects/`).subscribe({
      next: rows => { this.projects = rows; this.projectId = rows.find(p => p.is_demo)?.id || rows[0]?.id || ''; this.reloadManagerView(); },
      error: () => this.fail('Projects could not be loaded.'),
    });
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

  reloadManagerView(): void {
    if (!this.projectId) { this.loading = false; return; }
    this.loading = true;
    forkJoin({
      meetings: this.http.get<any[]>(`${API_V1_URL}/sales/projects/${this.projectId}/meetings`),
      leads: this.http.get<any[]>(`${API_V1_URL}/sales/projects/${this.projectId}/leads-report`),
      brokers: this.http.get<any[]>(`${API_V1_URL}/brokers/${this.projectId}/brokers`),
    }).subscribe({
      next: data => { this.meetings = data.meetings; this.leads = data.leads; this.brokers = data.brokers; this.loading = false; this.cdr.markForCheck(); },
      error: () => this.fail('Sales calendar data could not be loaded.'),
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
    const [sh, sm] = this.blockStart.split(':').map(Number); const [eh, em] = this.blockEnd.split(':').map(Number);
    const startsAt = new Date(this.selectedDay); const endsAt = new Date(this.selectedDay);
    startsAt.setHours(sh, sm, 0, 0); endsAt.setHours(eh, em, 0, 0); this.availabilitySaving = true;
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
    this.selected = meeting; this.selectedDay = null; this.selectedLead = null;
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
    if (!this.selected) return; this.saving = true;
    this.http.put<any>(`${API_V1_URL}/sales/meetings/${this.selected.id}`, {
      broker_id: this.selected.broker_id || null, status: this.selected.status, confirmation_status: this.selected.confirmation_status,
    }).subscribe({
      next: row => { Object.assign(this.selected, row); this.saving = false; this.success = 'Meeting updated.'; this.cdr.markForCheck(); },
      error: err => { this.saving = false; this.error = err.error?.detail || 'Meeting could not be updated.'; this.cdr.markForCheck(); },
    });
  }

  get days(): Date[] { const start = new Date(this.month.getFullYear(), this.month.getMonth(), 1); const grid = new Date(start); grid.setDate(1 - start.getDay()); return Array.from({ length: 42 }, (_, i) => new Date(grid.getFullYear(), grid.getMonth(), grid.getDate() + i)); }
  meetingsFor(day: Date): any[] { return this.meetings.filter(item => new Date(item.meeting_time).toDateString() === day.toDateString()); }
  availabilityFor(day: Date): any[] { return this.availability.filter(item => this.utcDate(item.starts_at).toDateString() === day.toDateString()); }
  utcDate(value: string): Date { return new Date(/[zZ]|[+-]\d\d:\d\d$/.test(value) ? value : `${value}Z`); }
  move(delta: number): void { this.month = new Date(this.month.getFullYear(), this.month.getMonth() + delta, 1); this.selectedDay = null; this.selected = null; this.role === 'sales' ? this.loadSalesSchedule() : this.reloadManagerView(); }
  count(status: string): number { return this.meetings.filter(item => item.status === status).length; }
  trackById(_: number, item: any): string { return item.id; }
  objectEntries(value: any): { key: string; value: any }[] {
    return Object.entries(value || {}).map(([key, item]) => ({
      key,
      value: item && typeof item === 'object' ? JSON.stringify(item) : item,
    }));
  }
  private fail(message: string): void { this.loading = false; this.error = message; this.cdr.markForCheck(); }
}
