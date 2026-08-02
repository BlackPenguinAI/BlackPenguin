import { Component, OnInit, ChangeDetectorRef, isDevMode } from '@angular/core';
import { CommonModule, DatePipe, DecimalPipe } from '@angular/common';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { ToastService } from '../../../../core/services/toast';

import { GlassCardComponent } from '../../../../shared/ui/glass-card/glass-card';

@Component({
  selector: 'app-dashboard-page',
  standalone: true,
  imports: [CommonModule, GlassCardComponent],
  providers: [DatePipe, DecimalPipe],
  templateUrl: './dashboard-page.html'
})
export class DashboardPageComponent implements OnInit {
  stats: any = {
    total_companies: 0,
    total_tokens: 0,
    total_usd: 0,
    recent_companies: []
  };
  
  isLoading: boolean = true;

  constructor(
    private http: HttpClient,
    private toast: ToastService,
    private cdr: ChangeDetectorRef
  ) {}

  ngOnInit(): void {
    this.loadStats();
  }

  private get baseUrl() {
    return isDevMode() ? 'http://localhost:8000' : 'https://blackpenguin.ai';
  }

  private get headers() {
    const token = localStorage.getItem('bp_token');
    return new HttpHeaders().set('Authorization', `Bearer ${token}`);
  }

  loadStats(): void {
    this.isLoading = true;
    this.http.get<any>(`${this.baseUrl}/api/v1/system/stats/`, { headers: this.headers }).subscribe({
      next: (data) => {
        if (data) {
          this.stats = data;
        }
        this.isLoading = false;
        this.cdr.detectChanges();
      },
      error: (err) => {
        this.toast.showError('Failed to load dashboard statistics.');
        this.isLoading = false;
        this.cdr.detectChanges();
      }
    });
  }
}