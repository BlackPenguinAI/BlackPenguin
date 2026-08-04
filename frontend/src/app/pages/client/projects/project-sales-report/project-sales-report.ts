import { CommonModule } from '@angular/common';
import { ChangeDetectorRef, Component, OnInit } from '@angular/core';
import { ActivatedRoute, RouterModule } from '@angular/router';

import { SalesReport } from '../project-overview/project-overview.models';
import { ProjectOverviewService } from '../project-overview/project-overview.service';

@Component({
  selector: 'app-project-sales-report',
  standalone: true,
  imports: [CommonModule, RouterModule],
  templateUrl: './project-sales-report.html',
  styleUrls: ['./project-sales-report.scss'],
})
export class ProjectSalesReportComponent implements OnInit {
  projectId = '';
  report: SalesReport | null = null;
  isLoading = true;
  errorMessage = '';

  constructor(
    private readonly route: ActivatedRoute,
    private readonly service: ProjectOverviewService,
    private readonly cdr: ChangeDetectorRef,
  ) {}

  ngOnInit(): void {
    this.projectId = this.route.snapshot.paramMap.get('id') || '';
    this.service.getSalesReport(this.projectId).subscribe({
      next: (report) => { this.report = report; this.isLoading = false; this.cdr.detectChanges(); },
      error: () => { this.errorMessage = 'Sales Intelligence could not be loaded.'; this.isLoading = false; this.cdr.detectChanges(); },
    });
  }

  formatMoney(value: number | null): string {
    return value == null ? 'Pending' : new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(value);
  }
}
