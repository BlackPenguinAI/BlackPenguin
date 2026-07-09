import { Component, OnInit, isDevMode } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { HttpClient } from '@angular/common/http';
import { ActivatedRoute, Router } from '@angular/router';
import { TranslateModule, TranslateService } from '@ngx-translate/core';
import { ToastService } from '../../core/services/toast';

@Component({
  selector: 'app-set-password',
  standalone: true,
  imports: [CommonModule, FormsModule, TranslateModule],
  templateUrl: './set-password.html'
})
export class SetPasswordComponent implements OnInit {
  token: string | null = null;
  form = { new_password: '', confirm_password: '' };
  isLoading: boolean = false;
  
  constructor(
    private route: ActivatedRoute,
    private router: Router,
    private http: HttpClient,
    private toast: ToastService,
    public translate: TranslateService
  ) {}

  ngOnInit() {
    // Extraer el token de la URL: ?token=...
    this.route.queryParams.subscribe(params => {
      this.token = params['token'];
      if (!this.token) {
        this.toast.showError('Token no proporcionado.');
        this.router.navigate(['/login']);
      }
    });
  }

  submitPassword() {
    if (this.form.new_password !== this.form.confirm_password) {
      this.toast.showError(this.translate.instant('PROFILE_PAGE.MSG_PASS_MISMATCH') || 'Las contraseñas no coinciden.');
      return;
    }

    if (!this.token) return;
    this.isLoading = true;

    const url = isDevMode() ? 'http://localhost:8000/api/v1/auth/set-password' : 'https://blackpenguin.ai/api/v1/auth/set-password';

    this.http.post(url, { token: this.token, new_password: this.form.new_password }).subscribe({
      next: () => {
        this.isLoading = false;
        this.toast.showSuccess('¡Contraseña establecida con éxito! Ya puedes iniciar sesión.');
        this.router.navigate(['/login']);
      },
      error: (err) => {
        this.isLoading = false;
        this.toast.showError(err.error?.detail || 'Error al validar el enlace.');
      }
    });
  }
}