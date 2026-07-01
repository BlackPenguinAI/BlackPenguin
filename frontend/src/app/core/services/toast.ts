import { Injectable } from '@angular/core';
import { BehaviorSubject } from 'rxjs';

export interface ToastMessage { message: string; type: 'success' | 'error'; }

@Injectable({ providedIn: 'root' })
export class ToastService {
  toast$ = new BehaviorSubject<ToastMessage | null>(null);

  showError(message: string) {
    this.toast$.next({ message, type: 'error' });
    setTimeout(() => this.toast$.next(null), 4000);
  }

  showSuccess(message: string) {
    this.toast$.next({ message, type: 'success' });
    setTimeout(() => this.toast$.next(null), 4000);
  }
}