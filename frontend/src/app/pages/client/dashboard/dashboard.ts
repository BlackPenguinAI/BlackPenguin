import { Component, OnInit, ChangeDetectorRef } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule } from '@angular/router'; // 🚀 Requerido para que funcionen los routerLink
import { DashboardService } from './dashboard.service';

@Component({
  selector: 'app-dashboard',
  standalone: true,
  imports: [CommonModule, RouterModule],
  templateUrl: './dashboard.html',
  styleUrls: ['./dashboard.scss']
})
export class Dashboard implements OnInit {
  isLoading: boolean = true;
  loadError = false;
  
  stats = {
    projects_count: 0,
    leads_count: 0,
    ai_interactions_count: 0
  };

  constructor(
    private dashboardService: DashboardService,
    private cdr: ChangeDetectorRef
  ) {}

  ngOnInit(): void {
    this.loadStats();
  }

  loadStats() {
    this.isLoading = true;
    this.loadError = false;
    this.dashboardService.getStats().subscribe({
      next: (data) => {
        this.stats = {
          projects_count: data.projects.active,
          leads_count: data.leads.current_month,
          ai_interactions_count: data.ai_interactions.current_month,
        };
        this.isLoading = false;
        this.cdr.detectChanges(); // 🚀 Obligamos a pintar la pantalla
      },
      error: (err) => {
        console.error('Error loading dashboard stats', err);
        this.isLoading = false;
        this.loadError = true;
        this.cdr.detectChanges();
      }
    });
  }
}
