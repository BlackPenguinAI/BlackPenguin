import { Component, OnInit, isDevMode, ChangeDetectorRef } from '@angular/core'; // 🚀 IMPORTANTE: Añadido ChangeDetectorRef
import { CommonModule } from '@angular/common';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { TranslateModule } from '@ngx-translate/core';
import { RouterModule } from '@angular/router';

@Component({
  selector: 'app-staff-dashboard',
  standalone: true,
  imports: [CommonModule, TranslateModule, RouterModule],
  templateUrl: './dashboard.html', 
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

  // 🚀 INYECCIÓN: Agregamos cdr al constructor maestro
  constructor(
    private http: HttpClient,
    private cdr: ChangeDetectorRef 
  ) {}

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

    // 🚀 Sincronizamos preventivamente el nombre desde el localStorage actualizado
    this.adminName = localStorage.getItem('bp_name') || 'Staff';
    
    const token = localStorage.getItem('bp_token');
    const headers = new HttpHeaders().set('Authorization', `Bearer ${token}`);

    this.http.get<any>(this.apiUrl, { headers }).subscribe({
      next: (data) => {
        this.stats = {
          total_companies: data.total_companies || 0,
          active_companies: data.active_companies || 0,
          total_projects: data.total_projects || 0,
          total_waitlist: data.total_waitlist || 0,
          total_users: data.total_users || 0,
          system_status: data.system_status || 'Operational'
        };

        // 🚀 Si el backend en las estadísticas incluyera opcionalmente el nombre del admin conectado, lo leemos
        if (data.admin_name) {
          this.adminName = data.admin_name;
          localStorage.setItem('bp_name', data.admin_name);
        } else {
          // Si no, volvemos a leer la llave para asegurar consistencia tras el guardado
          this.adminName = localStorage.getItem('bp_name') || 'Staff';
        }
        
        this.isLoading = false;
        
        // 🚀 OBLIGAMOS A ANGULAR A OCULTAR EL SPINNER Y MOSTRAR LOS DATOS EN VIVO
        this.cdr.detectChanges(); 
      },
      error: (err) => {
        console.error('❌ Error al consultar métricas del Dashboard global:', err); // ✅ ESTO ES TYPESCRIPT
        this.stats.system_status = 'Error';
        this.isLoading = false;
        
        // 🚀 OBLIGAMOS A ANGULAR A ACTUALIZAR EN CASO DE FALLA
        this.cdr.detectChanges(); 
      }
    });
  }
}