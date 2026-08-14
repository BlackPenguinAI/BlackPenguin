import { CommonModule } from '@angular/common';
import { ChangeDetectorRef, Component, OnDestroy, OnInit } from '@angular/core';
import { Router, RouterModule } from '@angular/router';
import { HttpErrorResponse } from '@angular/common/http';

import { CompanyOverview } from './company-overview.models';
import { CompanyOverviewService } from './company-overview.service';

@Component({
  selector: 'app-company-overview',
  standalone: true,
  imports: [CommonModule, RouterModule],
  templateUrl: './company-overview.html',
  styleUrls: ['./company-overview.scss'],
})
export class CompanyOverviewComponent implements OnInit, OnDestroy {
  overview: CompanyOverview | null = null;
  logoObjectUrl: string | null = null;
  loading = true;
  errorMessage = '';

  constructor(
    private readonly service: CompanyOverviewService,
    private readonly cdr: ChangeDetectorRef,
    private readonly router: Router,
  ) {}

  ngOnInit(): void {
    this.service.getOverview().subscribe({
      next: overview => {
        this.overview = overview; this.loading = false;
        if (overview.logo_url) this.loadLogo(overview.logo_url);
        this.cdr.detectChanges();
      },
      error: (error: HttpErrorResponse) => {
        if (error.status === 409) {
          this.router.navigateByUrl('/app/company/onboarding', { replaceUrl: true });
          return;
        }
        this.loading = false;
        this.errorMessage = 'The Company Overview could not be loaded.';
        this.cdr.detectChanges();
      },
    });
  }

  ngOnDestroy(): void { if (this.logoObjectUrl) URL.revokeObjectURL(this.logoObjectUrl); }

  list(value: unknown): string {
    if (Array.isArray(value)) return value.join(', ');
    return typeof value === 'string' ? value : value ? JSON.stringify(value) : 'Pending';
  }

  emailHref(email: string): string { return `mailto:${email.trim()}`; }

  phoneHref(phone: string): string {
    const normalized = phone.trim().replace(/(?!^\+)\D/g, '');
    return `tel:${normalized}`;
  }

  socialNetwork(url: string): string {
    const host = this.safeHost(url);
    if (host.includes('linkedin.')) return 'LinkedIn';
    if (host.includes('instagram.')) return 'Instagram';
    if (host.includes('facebook.')) return 'Facebook';
    if (host === 'x.com' || host.endsWith('.x.com') || host.includes('twitter.')) return 'X';
    if (host.includes('youtube.') || host.includes('youtu.be')) return 'YouTube';
    if (host.includes('tiktok.')) return 'TikTok';
    if (host.includes('pinterest.')) return 'Pinterest';
    return host.replace(/^www\./, '') || 'Social profile';
  }

  socialMark(url: string): string {
    return ({ LinkedIn: 'in', Instagram: '◎', Facebook: 'f', X: '𝕏', YouTube: '▶', TikTok: '♪', Pinterest: 'P' } as Record<string, string>)[this.socialNetwork(url)] || '↗';
  }

  private safeHost(url: string): string {
    try { return new URL(url).hostname.toLowerCase(); } catch { return ''; }
  }

  private loadLogo(url: string): void {
    this.service.getLogo(url).subscribe({ next: blob => { this.logoObjectUrl = URL.createObjectURL(blob); this.cdr.detectChanges(); } });
  }
}
