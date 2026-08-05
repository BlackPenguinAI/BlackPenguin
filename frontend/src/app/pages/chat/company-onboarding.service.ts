import { HttpClient } from '@angular/common/http';
import { Injectable, isDevMode } from '@angular/core';
import { Observable } from 'rxjs';

import {
  ChatMessage,
  ChatTurnResponse,
  CompanyProfileResponse,
  OnboardingSource,
  OnboardingState,
  ProposalDecisionResponse,
} from './company-onboarding.models';

@Injectable({ providedIn: 'root' })
export class CompanyOnboardingService {
  private readonly baseUrl = isDevMode()
    ? 'http://localhost:8000/api/v1/company-onboarding'
    : '/api/v1/company-onboarding';

  constructor(private readonly http: HttpClient) {}

  getProfile(): Observable<CompanyProfileResponse> {
    return this.http.get<CompanyProfileResponse>(`${this.baseUrl}/profile`);
  }

  getHistory(): Observable<ChatMessage[]> {
    return this.http.get<ChatMessage[]>(`${this.baseUrl}/chat`);
  }

  startChat(): Observable<ChatTurnResponse> {
    return this.http.post<ChatTurnResponse>(`${this.baseUrl}/chat/start`, {});
  }

  bootstrap(initialUrl: string): Observable<ChatTurnResponse> {
    return this.http.post<ChatTurnResponse>(`${this.baseUrl}/chat/bootstrap`, {
      initial_url: initialUrl,
      skip_website: false,
    });
  }

  getState(): Observable<OnboardingState> {
    return this.http.get<OnboardingState>(`${this.baseUrl}/chat/state`);
  }

  sendMessage(message: string, inReplyToMessageId?: string | null): Observable<ChatTurnResponse> {
    return this.http.post<ChatTurnResponse>(`${this.baseUrl}/chat`, { message, in_reply_to_message_id: inReplyToMessageId || null });
  }

  getSources(): Observable<OnboardingSource[]> {
    return this.http.get<OnboardingSource[]>(`${this.baseUrl}/sources`);
  }

  uploadFiles(files: File[]): Observable<OnboardingSource[]> {
    const body = new FormData();
    files.forEach((file) => body.append('files', file, file.name));
    return this.http.post<OnboardingSource[]>(`${this.baseUrl}/sources/files`, body);
  }

  decideProposal(
    proposalId: string,
    action: 'confirm' | 'correct' | 'reject',
    value?: unknown,
  ): Observable<ProposalDecisionResponse> {
    return this.http.post<ProposalDecisionResponse>(
      `${this.baseUrl}/proposals/${proposalId}/decision`,
      { action, value },
    );
  }

  downloadAttachment(url: string): Observable<Blob> {
    return this.http.get(url, { responseType: 'blob' });
  }
}
