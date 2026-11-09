import { ChangeDetectorRef, Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { HttpClient } from '@angular/common/http';
import { Router, RouterLink } from '@angular/router';
import { API_V1_URL } from '../../../../core/config/api.config';
import { OnboardingWelcomeComponent, normalizeOnboardingUrl } from '../../../../shared/ui/onboarding-welcome/onboarding-welcome';

interface StartChoice { client_request_id: string; initial_url: string | null; skip_website: boolean; }

@Component({
  selector: 'app-project-new', standalone: true,
  imports: [CommonModule, RouterLink, OnboardingWelcomeComponent],
  template: `
    <a routerLink="/app/projects" class="inline-block p-4 text-sm text-gray-400">← Back to Projects</a>
    <p *ngIf="errorMessage" role="alert" class="mx-auto max-w-2xl px-4 text-red-300">{{ errorMessage }}</p>
    <app-onboarding-welcome kind="project" [firstName]="firstName" [busy]="busy"
      (continueWithUrl)="start($event)" (skip)="start(null)"></app-onboarding-welcome>
  `,
})
export class ProjectNewComponent {
  busy = false;
  errorMessage = '';
  firstName = (localStorage.getItem('bp_name') || '').trim().split(/\s+/)[0];
  private pending = new Map<string, StartChoice>();

  constructor(private http: HttpClient, private router: Router, private cdr: ChangeDetectorRef) {}

  start(rawUrl: string | null): void {
    if (this.busy) return;
    const url = rawUrl === null ? null : normalizeOnboardingUrl(rawUrl);
    if (url !== null) {
      try {
        const parsed = new URL(url);
        if (!['http:', 'https:'].includes(parsed.protocol) || !parsed.hostname) throw new Error();
      } catch { this.errorMessage = 'Enter a valid HTTP or HTTPS project website.'; return; }
    }
    const storageKey = 'bp_project_start:' + (localStorage.getItem('bp_user_id') || '') + ':' + (url ?? 'no-website');
    let choice = this.pending.get(storageKey);
    if (!choice) {
      let requestId: string | null = null;
      try { requestId = sessionStorage.getItem(storageKey); } catch { /* Retry still works in memory. */ }
      choice = {client_request_id: requestId || crypto.randomUUID(), initial_url: url, skip_website: url === null};
      this.pending.set(storageKey, choice);
      try { sessionStorage.setItem(storageKey, choice.client_request_id); } catch { /* Storage may be disabled. */ }
    }
    this.busy = true;
    this.errorMessage = '';
    this.http.post<{id: string; onboarding_url: string}>(`${API_V1_URL}/projects/start`, choice).subscribe({
      next: async created => {
        try {
          if (await this.router.navigateByUrl(created.onboarding_url)) {
            this.pending.delete(storageKey);
            try { sessionStorage.removeItem(storageKey); } catch { /* Navigation already succeeded. */ }
          } else this.errorMessage = 'The project was started. Retry to reopen the same onboarding.';
        } catch { this.errorMessage = 'The project was started. Retry to reopen the same onboarding.'; }
        finally { this.busy = false; this.cdr.markForCheck(); }
      },
      error: error => {
        const detail = error.error?.detail;
        this.errorMessage = typeof detail === 'string' ? detail : 'The project could not be started. Retry; the same request will be reused.';
        this.busy = false;
        this.cdr.markForCheck();
      },
    });
  }
}
