import { Component, OnInit, ChangeDetectorRef } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule } from '@angular/router';
import { TranslateModule } from '@ngx-translate/core';

import { DashboardService } from './../services/dashboard';
import { GlassCardComponent } from '../../../../shared/ui/glass-card/glass-card';

@Component({
  selector: 'app-admin-dashboard-page',
  standalone: true,
  imports: [CommonModule, RouterModule, TranslateModule, GlassCardComponent],
  templateUrl: './dashboard-page.html'
})
export class DashboardPageComponent implements OnInit {
  stats: any = {
    total_companies: 0,
    active_companies: 0,
    total_projects: 0,
    total_waitlist: 0,
    total_users: 0,
    system_status: 'Cargando...'
  };
  
  adminName: string = '';
  isLoading: boolean = true;
  currentDate: Date = new Date();

  constructor(
    private dashboardService: DashboardService,
    private cdr: ChangeDetectorRef 
  ) {}

  ngOnInit() {
    this.adminName = localStorage.getItem('bp_name') || 'Staff';
    this.loadStats();
  }

  loadStats() {
    this.isLoading = true;
    this.dashboardService.getAdminStats().subscribe({
      next: (data) => {
        this.stats = {
          total_companies: data.total_companies || 0,
          active_companies: data.active_companies || 0,
          total_projects: data.total_projects || 0,
          total_waitlist: data.total_waitlist || 0,
          total_users: data.total_users || 0,
          system_status: data.system_status || 'Operational'
        };

        if (data.admin_name) {
          this.adminName = data.admin_name;
          localStorage.setItem('bp_name', data.admin_name);
        }
        
        this.isLoading = false;
        this.cdr.detectChanges(); 
      },
      error: (err) => {
        console.error('Error al consultar métricas del Dashboard global:', err);
        this.stats.system_status = 'Error';
        this.isLoading = false;
        this.cdr.detectChanges(); 
      }
    });
  }
}