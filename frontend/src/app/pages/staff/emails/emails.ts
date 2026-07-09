import { Component, OnInit, Inject, PLATFORM_ID, isDevMode } from '@angular/core';
import { isPlatformBrowser, CommonModule } from '@angular/common';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { FormsModule } from '@angular/forms'; // 🚀 Necesario para el [(ngModel)] de edición
import { TranslateModule, TranslateService } from '@ngx-translate/core'; // 🚀 Para idiomas
import * as XLSX from 'xlsx'; // 🚀 Librería de Excel
import { ToastService } from '../../../core/services/toast'; // 🚀 Importar el servicio Toast de tu app

@Component({
  selector: 'app-staff-emails',
  standalone: true,
  imports: [CommonModule, FormsModule, TranslateModule],
  templateUrl: './emails.html',
  styleUrl: './emails.scss'
})
export class StaffEmailsComponent implements OnInit {
  emails: { id: string; email: string; created_at: string }[] = [];
  isLoading: boolean = true;
  errorMsg: string = '';
  
  // Variables para Edición (CRUD)
  editingId: string | null = null;
  editEmailValue: string = '';

  showDeleteModal: boolean = false;
  emailToDelete: string | null = null;
  isDeleting: boolean = false;

  constructor(
    private http: HttpClient,
    private translate: TranslateService,
    private toast: ToastService, // 🚀 Inyectar servicio de Toasts,
    @Inject(PLATFORM_ID) private platformId: Object // 🚀 Inyectamos el detector de entorno
  ) {}

  ngOnInit() {
    // 🚀 SOLUCIÓN AL F5: Solo carga los datos si está en el Navegador del cliente, no en SSR
    if (isPlatformBrowser(this.platformId)) {
      this.loadData();
    } else {
      this.isLoading = false;
    }
  }

  private get apiUrl() {
    return isDevMode() 
      ? 'http://localhost:8000/api/v1/leads/waitlist' 
      : 'https://blackpenguin.ai/api/v1/leads/waitlist';
  }

  private get headers() {
    const token = localStorage.getItem('bp_token');
    return new HttpHeaders().set('Authorization', `Bearer ${token}`);
  }

  loadData() {
    this.isLoading = true;
    this.http.get<any[]>(this.apiUrl, { headers: this.headers }).subscribe({
      next: (data) => {
        this.emails = data;
        this.isLoading = false;
      },
      error: (err) => {
        this.errorMsg = 'No tienes permisos o tu sesión expiró.';
        this.isLoading = false;
      }
    });
  }

  // --- MÉTODOS DEL CRUD ---
  startEdit(item: any) {
    this.editingId = item.id;
    this.editEmailValue = item.email;
  }

  cancelEdit() {
    this.editingId = null;
    this.editEmailValue = '';
  }

  saveEdit(id: string) {
    if (!this.editEmailValue.trim()) return;
    
    this.http.put(`${this.apiUrl}/${id}`, { email: this.editEmailValue }, { headers: this.headers }).subscribe({
      next: () => {
        this.loadData(); // Recarga la tabla
        this.editingId = null;
      },
      error: (err) => {
        alert(err.error?.detail || 'Error al actualizar');
      }
    });
  }

  openDeleteModal(id: string) {
    this.emailToDelete = id;
    this.showDeleteModal = true;
  }

  closeDeleteModal() {
    this.showDeleteModal = false;
    this.emailToDelete = null;
  }

  confirmDelete() {
    if (!this.emailToDelete) return;
    this.isDeleting = true;

    // Asegúrate de que esta sea la ruta correcta a tu API de emails/waitlist
    this.http.delete(`${this.apiUrl}/${this.emailToDelete}`, { headers: this.headers }).subscribe({
      next: () => {
        this.isDeleting = false;
        this.closeDeleteModal();
        this.loadData(); // O como se llame tu función que recarga la tabla
        this.toast.showSuccess('Registro eliminado exitosamente.');
      },
      error: (err) => {
        this.isDeleting = false;
        this.closeDeleteModal();
        this.toast.showError(err.error?.detail || 'Error al eliminar el registro');
      }
    });
  }

  // --- EXPORTACIÓN A EXCEL ---
  exportToExcel() {
    // 1. Mapeamos la data para que los encabezados del Excel salgan traducidos
    const dataToExport = this.emails.map(item => ({
      [this.translate.instant('ADMIN.COL_ID') || 'ID']: item.id,
      [this.translate.instant('ADMIN.COL_EMAIL') || 'Email']: item.email,
      [this.translate.instant('ADMIN.COL_DATE') || 'Date (UTC)']: item.created_at
    }));

    // 2. Construimos el Excel
    const ws: XLSX.WorkSheet = XLSX.utils.json_to_sheet(dataToExport);
    const wb: XLSX.WorkBook = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, 'Waitlist');
    
    // 3. Forzamos la descarga del archivo con la fecha de hoy
    const fileName = `BlackPenguin_Waitlist_${new Date().toISOString().slice(0, 10)}.xlsx`;
    XLSX.writeFile(wb, fileName);
  }
}