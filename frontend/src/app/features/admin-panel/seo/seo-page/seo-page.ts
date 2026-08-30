import { ChangeDetectorRef, Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { HttpClient } from '@angular/common/http';
import { API_V1_URL } from '../../../../core/config/api.config';
import { ToastService } from '../../../../core/services/toast';

@Component({ selector: 'app-seo-page', standalone: true, imports: [CommonModule], templateUrl: './seo-page.html', styleUrl: './seo-page.scss' })
export class SeoPageComponent implements OnInit {
  audits: any[] = [];
  loading = true;
  running = false;
  constructor(private http: HttpClient, private toast: ToastService, private cdr: ChangeDetectorRef) {}
  ngOnInit(): void { this.load(); }
  load(): void { this.http.get<any[]>(`${API_V1_URL}/seo/audits`).subscribe({ next: rows => { this.audits = rows; this.loading = false; this.cdr.markForCheck(); }, error: () => { this.loading = false; this.toast.showError('Could not load SEO audits.'); } }); }
  run(): void { this.running = true; this.http.post<any>(`${API_V1_URL}/seo/audits`, {}).subscribe({ next: item => { this.audits = [item, ...this.audits]; this.running = false; this.toast.showSuccess('Technical SEO audit completed.'); this.cdr.markForCheck(); }, error: err => { this.running = false; this.toast.showError(err.error?.detail || 'SEO audit failed.'); this.cdr.markForCheck(); } }); }
  entries(value: any): { key: string; value: any }[] { return Object.entries(value || {}).map(([key, item]) => ({ key, value: item })); }
}
