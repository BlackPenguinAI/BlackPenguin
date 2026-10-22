import { CommonModule } from '@angular/common';
import { ChangeDetectorRef, Component, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { HttpClient } from '@angular/common/http';
import { API_V1_URL } from '../../../core/config/api.config';

@Component({ selector: 'app-export-audit', standalone: true, imports: [CommonModule, FormsModule], templateUrl: './export-audit.html', styleUrl: './export-audit.scss' })
export class ExportAuditComponent implements OnInit {
  companies: any[] = []; events: any[] = []; assetEvents: any[] = []; activeTab: 'exports' | 'materials' = 'exports';
  companyId = ''; exportType = ''; assetEventType = ''; assetChannel = ''; humanOnly = false; loading = true; error = ''; revoking = '';
  constructor(private http: HttpClient, private cdr: ChangeDetectorRef) {}
  ngOnInit(): void { this.http.get<any[]>(`${API_V1_URL}/companies/`).subscribe(rows => { this.companies = rows || []; }); this.load(); }
  load(): void {
    this.loading = true; this.error = '';
    const params = new URLSearchParams(); if (this.companyId) params.set('company_id', this.companyId);
    if (this.activeTab === 'exports' && this.exportType) params.set('export_type', this.exportType);
    if (this.activeTab === 'materials' && this.assetEventType) params.set('event_type', this.assetEventType);
    if (this.activeTab === 'materials' && this.assetChannel) params.set('channel', this.assetChannel);
    if (this.activeTab === 'materials' && this.humanOnly) params.set('human_only', 'true');
    const endpoint = this.activeTab === 'exports' ? 'export-audit' : 'sales-asset-audit';
    this.http.get<any[]>(`${API_V1_URL}/governance/admin/${endpoint}?${params}`).subscribe({
      next: rows => { if (this.activeTab === 'exports') this.events = rows || []; else this.assetEvents = rows || []; this.loading = false; this.cdr.markForCheck(); },
      error: err => { this.error = err.error?.detail || 'Audit events could not be loaded.'; this.loading = false; this.cdr.markForCheck(); },
    });
  }
  companyName(id: string): string { return this.companies.find(item => item.id === id)?.name || id || 'Platform'; }
  short(value: string): string { return value ? `${value.slice(0, 10)}…${value.slice(-8)}` : '—'; }
  selectTab(tab: 'exports' | 'materials'): void { this.activeTab = tab; this.load(); }
  revoke(event: any): void {
    if (!event.share_id || event.share_revoked || this.revoking) return;
    this.revoking = event.share_id; this.error = '';
    this.http.post(`${API_V1_URL}/governance/admin/sales-asset-shares/${event.share_id}/revoke`, {}).subscribe({
      next: () => { this.revoking = ''; this.load(); },
      error: err => { this.revoking = ''; this.error = err.error?.detail || 'The shared link could not be revoked.'; this.cdr.markForCheck(); },
    });
  }
}
