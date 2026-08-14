import { CommonModule } from '@angular/common';
import { ChangeDetectorRef, Component, OnDestroy, OnInit } from '@angular/core';
import { RouterModule } from '@angular/router';

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

  constructor(private readonly service: CompanyOverviewService, private readonly cdr: ChangeDetectorRef) {}

  ngOnInit(): void {
    this.service.getOverview().subscribe({
      next: overview => {
        this.overview = overview; this.loading = false;
        if (overview.logo_url) this.loadLogo(overview.logo_url);
        this.cdr.detectChanges();
      },
      error: () => { this.loading = false; this.errorMessage = 'The Company Overview could not be loaded.'; this.cdr.detectChanges(); },
    });
  }

  ngOnDestroy(): void { if (this.logoObjectUrl) URL.revokeObjectURL(this.logoObjectUrl); }

  list(value: unknown): string {
    if (Array.isArray(value)) return value.join(', ');
    return typeof value === 'string' ? value : value ? JSON.stringify(value) : 'Pending';
  }

  private loadLogo(url: string): void {
    this.service.getLogo(url).subscribe({ next: blob => { this.logoObjectUrl = URL.createObjectURL(blob); this.cdr.detectChanges(); } });
  }
}
