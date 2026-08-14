import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { API_V1_URL } from '../../../core/config/api.config';
import { CompanyOverview } from './company-overview.models';

@Injectable({ providedIn: 'root' })
export class CompanyOverviewService {
  constructor(private readonly http: HttpClient) {}
  getOverview(): Observable<CompanyOverview> {
    return this.http.get<CompanyOverview>(`${API_V1_URL}/company-onboarding/overview`);
  }
  getLogo(url: string): Observable<Blob> {
    return this.http.get(url, { responseType: 'blob' });
  }
}
