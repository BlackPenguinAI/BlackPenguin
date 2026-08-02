import { HttpClient, HttpHeaders } from '@angular/common/http';
import { Injectable, isDevMode } from '@angular/core';
import { Observable } from 'rxjs';

import {
  ChatMessage,
  ChatTurnResponse,
  CompanyProfileResponse,
  OnboardingSource,
  ProposalDecisionResponse,
} from './company-onboarding.models';

@Injectable({ providedIn: 'root' })
export class CompanyOnboardingService {
  private readonly baseUrl = isDevMode()
    ? 'http://localhost:8000/api/v1/company-onboarding'
    : '/api/v1/company-onboarding';

  constructor(private readonly http: HttpClient) {}

  getProfile(): Observable<CompanyProfileResponse> {
    return this.http.get<CompanyProfileResponse>(`${this.baseUrl}/profile`, this.options());
  }

  getHistory(): Observable<ChatMessage[]> {
    return this.http.get<ChatMessage[]>(`${this.baseUrl}/chat`, this.options());
  }

  startChat(): Observable<ChatTurnResponse> {
    return this.http.post<ChatTurnResponse>(`${this.baseUrl}/chat/start`, {}, this.options());
  }

  sendMessage(message: string): Observable<ChatTurnResponse> {
    return this.http.post<ChatTurnResponse>(`${this.baseUrl}/chat`, { message }, this.options());
  }

  getSources(): Observable<OnboardingSource[]> {
    return this.http.get<OnboardingSource[]>(`${this.baseUrl}/sources`, this.options());
  }

  uploadFiles(files: File[]): Observable<OnboardingSource[]> {
    const body = new FormData();
    files.forEach((file) => body.append('files', file, file.name));
    return this.http.post<OnboardingSource[]>(`${this.baseUrl}/sources/files`, body, this.options());
  }

  decideProposal(
    proposalId: string,
    action: 'confirm' | 'correct' | 'reject',
    value?: unknown,
  ): Observable<ProposalDecisionResponse> {
    return this.http.post<ProposalDecisionResponse>(
      `${this.baseUrl}/proposals/${proposalId}/decision`,
      { action, value },
      this.options(),
    );
  }

  private options(): { headers: HttpHeaders } {
    const token = localStorage.getItem('bp_token');
    return {
      headers: token
        ? new HttpHeaders().set('Authorization', `Bearer ${token}`)
        : new HttpHeaders(),
    };
  }
}
