import { CommonModule } from '@angular/common';
import { ChangeDetectorRef, Component, OnDestroy, OnInit } from '@angular/core';
import { ActivatedRoute, RouterModule } from '@angular/router';
import { DomSanitizer, SafeResourceUrl } from '@angular/platform-browser';

import { ProjectOverview } from './project-overview.models';
import { ProjectOverviewService } from './project-overview.service';

@Component({
  selector: 'app-project-overview',
  standalone: true,
  imports: [CommonModule, RouterModule],
  templateUrl: './project-overview.html',
  styleUrls: ['./project-overview.scss'],
})
export class ProjectOverviewComponent implements OnInit, OnDestroy {
  projectId = '';
  overview: ProjectOverview | null = null;
  coverObjectUrl: string | null = null;
  isLoading = true;
  errorMessage = '';
  mapSafeUrl: SafeResourceUrl | null = null;

  constructor(
    private readonly route: ActivatedRoute,
    private readonly overviewService: ProjectOverviewService,
    private readonly cdr: ChangeDetectorRef,
    private readonly sanitizer: DomSanitizer,
  ) {}

  ngOnInit(): void {
    this.projectId = this.route.snapshot.paramMap.get('id') || '';
    this.overviewService.getOverview(this.projectId).subscribe({
      next: (overview) => {
        this.overview = overview; this.isLoading = false;
        this.mapSafeUrl = this.buildMapUrl(overview);
        if (overview.cover_image_url) this.loadCover(overview.cover_image_url);
        this.cdr.detectChanges();
      },
      error: () => { this.isLoading = false; this.errorMessage = 'The Project Overview could not be loaded.'; this.cdr.detectChanges(); },
    });
  }

  ngOnDestroy(): void {
    if (this.coverObjectUrl) URL.revokeObjectURL(this.coverObjectUrl);
  }

  get locationLabel(): string {
    if (!this.overview) return 'Pending';
    return [this.overview.address, this.overview.city, this.overview.country].filter(Boolean).join(', ') || 'Pending';
  }

  private buildMapUrl(overview: ProjectOverview): SafeResourceUrl | null {
    const location = overview.location;
    if (!location) return null;
    const query = location.latitude != null && location.longitude != null
      ? `${location.latitude},${location.longitude}` : location.address;
    return query ? this.sanitizer.bypassSecurityTrustResourceUrl(`https://www.google.com/maps?q=${encodeURIComponent(query)}&output=embed`) : null;
  }

  formatMoney(value: number | null, currency?: string | null): string {
    if (value == null) return 'Pending';
    return new Intl.NumberFormat('en-US', { style: 'currency', currency: currency || 'USD', maximumFractionDigits: 0 }).format(value);
  }

  private loadCover(url: string): void {
    this.overviewService.getCover(url).subscribe({
      next: (blob) => { this.coverObjectUrl = URL.createObjectURL(blob); this.cdr.detectChanges(); },
    });
  }
}
