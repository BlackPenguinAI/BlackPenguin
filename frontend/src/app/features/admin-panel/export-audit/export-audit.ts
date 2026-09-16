import { CommonModule } from '@angular/common';
import { ChangeDetectorRef, Component, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { HttpClient } from '@angular/common/http';
import { API_V1_URL } from '../../../core/config/api.config';

@Component({ selector: 'app-export-audit', standalone: true, imports: [CommonModule, FormsModule], templateUrl: './export-audit.html', styleUrl: './export-audit.scss' })
export class ExportAuditComponent implements OnInit {
  companies: any[] = []; events: any[] = []; companyId = ''; exportType = ''; loading = true; error = '';
  constructor(private http: HttpClient, private cdr: ChangeDetectorRef) {}
  ngOnInit(): void { this.http.get<any[]>(`${API_V1_URL}/companies/`).subscribe(rows => { this.companies = rows || []; }); this.load(); }
  load(): void {
    this.loading = true; this.error = '';
    const params = new URLSearchParams(); if (this.companyId) params.set('company_id', this.companyId); if (this.exportType) params.set('export_type', this.exportType);
    this.http.get<any[]>(`${API_V1_URL}/governance/admin/export-audit?${params}`).subscribe({
      next: rows => { this.events = rows || []; this.loading = false; this.cdr.markForCheck(); },
      error: err => { this.error = err.error?.detail || 'Audit events could not be loaded.'; this.loading = false; this.cdr.markForCheck(); },
    });
  }
  companyName(id: string): string { return this.companies.find(item => item.id === id)?.name || id || 'Platform'; }
  short(value: string): string { return value ? `${value.slice(0, 10)}…${value.slice(-8)}` : '—'; }
}
