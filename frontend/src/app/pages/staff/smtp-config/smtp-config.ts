import { Component, OnInit, isDevMode, ChangeDetectorRef } from '@angular/core'; // 🚀 Importado ChangeDetectorRef
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { HttpClient, HttpHeaders } from '@angular/common/http';

@Component({
  selector: 'app-smtp-config',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './smtp-config.html'
})
export class SmtpConfigComponent implements OnInit {
  
  config = {
    smtp_host: '',
    smtp_port: 587,
    smtp_user: '',
    smtp_password: '',
    smtp_security: 'TLS',
    sender_email: ''
  };
  
  isSaving: boolean = false;
  statusMessage: string = '';
  isError: boolean = false;

  constructor(
    private http: HttpClient,
    private cdr: ChangeDetectorRef // 🚀 Inyectamos el control de renderizado
  ) {}

  private getUrl() {
    return isDevMode() 
      ? 'http://localhost:8000/api/v1/system/smtp-config' 
      : 'https://blackpenguin.ai/api/v1/system/smtp-config'; 
  }

  private getHeaders() {
    const token = localStorage.getItem('bp_token');
    return new HttpHeaders().set('Authorization', `Bearer ${token}`);
  }

  ngOnInit() {
    // Cargar configuración actual al iniciar
    this.http.get<any>(this.getUrl(), { headers: this.getHeaders() }).subscribe({
      next: (data) => { 
        if (data) {
          this.config = { ...this.config, ...data }; 
        }
        this.cdr.detectChanges(); // 🚀 Obligamos a rellenar los inputs del formulario en el DOM
      },
      error: () => {
        console.log('Aún no hay configuración SMTP guardada.');
        this.cdr.detectChanges(); // 🚀 Desbloqueamos el estado visual de carga si falla
      }
    });
  }

  onSave() {
    this.isSaving = true;
    this.statusMessage = '';
    this.isError = false;
    this.cdr.detectChanges(); // 🚀 Forzamos que el botón de submit muestre el estado "Guardando..."
    
    this.http.put(this.getUrl(), this.config, { headers: this.getHeaders() }).subscribe({
      next: () => {
        this.isSaving = false;
        this.isError = false;
        this.statusMessage = 'Configuración SMTP guardada exitosamente.';
        this.cdr.detectChanges(); // 🚀 Mostramos el texto de éxito de inmediato
        
        setTimeout(() => {
          this.statusMessage = '';
          this.cdr.detectChanges(); // 🚀 Limpiamos el mensaje de éxito del DOM
        }, 4000);
      },
      error: (err) => {
        this.isSaving = false;
        this.isError = true;
        this.statusMessage = err.error?.detail || 'Error al guardar la configuración.';
        this.cdr.detectChanges(); // 🚀 Pintamos el texto de error en la UI al instante
      }
    });
  }
}