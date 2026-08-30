import { Component } from '@angular/core';
import { RouterOutlet } from '@angular/router';
import { CommonModule } from '@angular/common'; // 🚀 Importante para *ngIf y [ngClass]
import { TranslateService } from '@ngx-translate/core';
import { ToastService } from './core/services/toast'; // 🚀 Importamos el servicio
import { SeoMetaService } from './core/services/seo-meta';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [RouterOutlet, CommonModule],
  template: `
    <router-outlet></router-outlet>
    
    <div *ngIf="toastService.toast$ | async as toast" 
         class="fixed top-6 right-6 z-[100] px-6 py-4 rounded-xl border backdrop-blur-xl shadow-2xl flex items-center gap-3 transition-all duration-300 animate-[fade-in_0.3s_ease-out]"
         [ngClass]="toast.type === 'error' ? 'bg-red-500/10 border-red-500/20 text-red-400' : 'bg-green-500/10 border-green-500/20 text-green-400'">
      <span class="material-symbols-outlined text-xl">{{ toast.type === 'error' ? 'error' : 'check_circle' }}</span>
      <span class="font-medium text-sm">{{ toast.message }}</span>
    </div>
  `
})
export class App {
  // 🚀 Inyectamos el ToastService para usarlo en el HTML
  constructor(private translate: TranslateService, public toastService: ToastService, seo: SeoMetaService) {
    this.translate.setDefaultLang('en');
    localStorage.setItem('bp_lang', 'en');
    this.translate.use('en');
    document.documentElement.lang = 'en';
    seo.start();
  }
}
