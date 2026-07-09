import { Component, OnInit, isDevMode } from '@angular/core';
import { CommonModule } from '@angular/common';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { TranslateModule } from '@ngx-translate/core';
import { RouterModule } from '@angular/router';

@Component({
  selector: 'app-staff-dashboard',
  standalone: true,
  imports: [CommonModule, TranslateModule, RouterModule],
  templateUrl: './dashboard.html', // <-- Asegúrate de que este nombre coincida con tu archivo HTML
  styleUrl: './dashboard.scss'
})
export class StaffDashboardComponent implements OnInit {
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

  constructor(private http: HttpClient) {}

  private get apiUrl() {
    return isDevMode() 
      ? 'http://localhost:8000/api/v1/tenants/stats' 
      : 'https://blackpenguin.ai/api/v1/tenants/stats';
  }

  ngOnInit() {
    this.adminName = localStorage.getItem('bp_name') || 'Staff';
    this.loadStats();
  }

  loadStats() {
    this.isLoading = true;
    const token = localStorage.getItem('bp_token');
    const headers = new HttpHeaders().set('Authorization', `Bearer ${token}`);

    this.http.get<any>(this.apiUrl, { headers }).subscribe({
      next: (data) => {
        this.stats = data;
        this.isLoading = false;
      },
      error: (err) => {
        console.error('Error al cargar métricas', err);
        this.stats.system_status = 'Desconectado';
        this.isLoading = false;
      }
    });
  }
}