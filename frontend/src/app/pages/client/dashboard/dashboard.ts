import { Component, OnInit, ChangeDetectorRef } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule } from '@angular/router'; // 🚀 Requerido para que funcionen los routerLink
import { AuthService } from '../../../core/services/auth';

@Component({
  selector: 'app-dashboard',
  standalone: true,
  imports: [CommonModule, RouterModule],
  templateUrl: './dashboard.html',
  styleUrls: ['./dashboard.scss']
})
export class Dashboard implements OnInit {
  isLoading: boolean = true;
  
  stats = {
    projects_count: 0,
    leads_count: 0,
    ai_interactions_count: 0
  };

  constructor(
    private authService: AuthService,
    private cdr: ChangeDetectorRef
  ) {}

  ngOnInit(): void {
    this.loadStats();
  }

  loadStats() {
    this.authService.getDashboardStats().subscribe({
      next: (data) => {
        this.stats = data;
        this.isLoading = false;
        this.cdr.detectChanges(); // 🚀 Obligamos a pintar la pantalla
      },
      error: (err) => {
        console.error('Error loading dashboard stats', err);
        this.isLoading = false;
        this.cdr.detectChanges();
      }
    });
  }
}