import { Component } from '@angular/core';
import { RouterOutlet } from '@angular/router';
import { CommonModule } from '@angular/common'; // 🚀 Importante para *ngIf y [ngClass]
import { TranslateService } from '@ngx-translate/core';
import { ToastService } from './core/services/toast'; // 🚀 Importamos el servicio

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [RouterOutlet, CommonModule],
  template: `
    <router-outlet></router-outlet>
    
    <div *ngIf="toastService.toast$ | async as toast" 
         class="fixed bottom-6 right-6 z-[100] max-w-xs rounded-full border px-4 py-2 text-xs font-medium shadow-xl backdrop-blur-xl transition-all duration-300 animate-[fade-in_0.3s_ease-out]"
         [ngClass]="toast.type === 'error' ? 'bg-black/70 border-red-400/20 text-red-300' : 'bg-black/70 border-green-400/20 text-green-300'">
      {{ toast.message }}
    </div>
  `
})
export class App {
  // 🚀 Inyectamos el ToastService para usarlo en el HTML
  constructor(private translate: TranslateService, public toastService: ToastService) {
    this.translate.setDefaultLang('en');
    const savedLang = localStorage.getItem('bp_lang') || 'en';
    this.translate.use(savedLang);
  }
}
