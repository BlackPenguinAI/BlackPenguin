import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { API_V1_URL } from '../../../../core/config/api.config';
import { ProjectOverview, SalesReport } from './project-overview.models';

@Injectable({ providedIn: 'root' })
export class ProjectOverviewService {
  constructor(private readonly http: HttpClient) {}

  getOverview(id: string): Observable<ProjectOverview> {
    return this.http.get<ProjectOverview>(`${API_V1_URL}/projects/${id}/overview`);
  }

  getCover(url: string): Observable<Blob> {
    return this.http.get(url, { responseType: 'blob' });
  }

  getSalesReport(id: string): Observable<SalesReport> {
    return this.http.get<SalesReport>(`${API_V1_URL}/sales/projects/${id}/sales-report`);
  }
}
