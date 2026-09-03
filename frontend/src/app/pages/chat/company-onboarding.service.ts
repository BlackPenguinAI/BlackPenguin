import { HttpClient, HttpHeaders } from '@angular/common/http';
import { Injectable, isDevMode } from '@angular/core';
import { Observable } from 'rxjs';

import { API_V1_URL } from '../../core/config/api.config';

import {
  ChatMessage,
  ChatTurnResponse,
  CompanyProfileResponse,
  OnboardingSource,
  OnboardingState,
  ProposalDecisionResponse,
  TeamMember,
  TeamMemberInvite,
  TeamOnboarding,
  CompanyMediaAsset,
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

  savePublicPresence(
    emails: string[], phones: string[], socialProfiles: string[],
    fields: string[] = ['public_contact_emails', 'public_contact_phones', 'corporate_social_profiles'],
  ): Observable<CompanyProfileResponse> {
    const selectedFields = new Set(fields);
    const updates = [
      { field: 'public_contact_emails', value: emails },
      { field: 'public_contact_phones', value: phones },
      { field: 'corporate_social_profiles', value: socialProfiles },
    ].filter(item => selectedFields.has(item.field)).map(item => ({
      field: item.field,
      value: item.value.length ? item.value : null,
      status: item.value.length ? 'confirmed' : 'deferred',
      applicable: true,
      source_type: 'user_input',
      source_reference: 'onboarding public presence card',
      confidence: 'high',
    }));
    return this.http.patch<CompanyProfileResponse>(`${this.baseUrl}/profile`, { updates });
  }

  deferPublicPresence(fields: string[] = ['public_contact_emails', 'public_contact_phones', 'corporate_social_profiles']): Observable<CompanyProfileResponse> {
    const updates = fields.map(field => ({
      field, value: null, status: 'deferred', applicable: true,
      source_type: 'user_input', source_reference: 'onboarding public presence deferred', confidence: 'high',
    }));
    return this.http.patch<CompanyProfileResponse>(`${this.baseUrl}/profile`, { updates });
  }

  useUrlAsOfficialWebsite(url: string): Observable<CompanyProfileResponse> {
    return this.http.patch<CompanyProfileResponse>(`${this.baseUrl}/profile`, {
      updates: [{
        field: 'official_corporate_website',
        value: { exists: true, url },
        status: 'confirmed',
        applicable: true,
        source_type: 'user_provided_url',
        source_reference: url,
        confidence: 'high',
      }],
    });
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

  getTeam(): Observable<TeamOnboarding> {
    return this.http.get<TeamOnboarding>(`${this.baseUrl}/team`);
  }

  createTeamMember(payload: TeamMemberInvite, idempotencyKey: string): Observable<TeamMember> {
    const headers = new HttpHeaders({ 'Idempotency-Key': idempotencyKey });
    return this.http.post<TeamMember>(`${this.baseUrl}/team/members`, payload, { headers });
  }

  continueTeamSetup(): Observable<OnboardingState> {
    return this.http.post<OnboardingState>(`${this.baseUrl}/team/continue`, {});
  }

  resendTeamMember(userId: string): Observable<{ detail: string }> {
    return this.http.post<{ detail: string }>(`${API_V1_URL}/users/company/${userId}/resend-activation`, {});
  }

  revokeTeamMember(userId: string): Observable<{ detail: string }> {
    return this.http.delete<{ detail: string }>(`${API_V1_URL}/users/company/${userId}/invitation`);
  }

  sendMessage(message: string, inReplyToMessageId?: string | null): Observable<ChatTurnResponse> {
    return this.http.post<ChatTurnResponse>(`${this.baseUrl}/chat`, { message, in_reply_to_message_id: inReplyToMessageId || null });
  }

  getSources(): Observable<OnboardingSource[]> {
    return this.http.get<OnboardingSource[]>(`${this.baseUrl}/sources`);
  }

  retrySource(sourceId: string): Observable<OnboardingSource> {
    return this.http.post<OnboardingSource>(`${this.baseUrl}/sources/${sourceId}/retry`, {});
  }

  uploadFiles(files: File[]): Observable<OnboardingSource[]> {
    const body = new FormData();
    files.forEach((file) => body.append('files', file, file.name));
    return this.http.post<OnboardingSource[]>(`${this.baseUrl}/sources/files`, body);
  }

  getMedia(): Observable<CompanyMediaAsset[]> {
    return this.http.get<CompanyMediaAsset[]>(`${this.baseUrl}/media`);
  }

  uploadLogo(file: File): Observable<CompanyMediaAsset> {
    const body = new FormData(); body.append('file', file, file.name);
    return this.http.post<CompanyMediaAsset>(`${this.baseUrl}/media/logo`, body);
  }

  selectLogo(assetId: string): Observable<CompanyMediaAsset> {
    return this.http.post<CompanyMediaAsset>(`${this.baseUrl}/media/${assetId}/logo`, {});
  }

  deferLogo(): Observable<CompanyProfileResponse> {
    return this.http.patch<CompanyProfileResponse>(`${this.baseUrl}/profile`, { updates: [{
      field: 'company_logo', value: null, status: 'deferred', applicable: true,
      source_type: 'user_input', source_reference: 'company logo deferred', confidence: 'high',
    }] });
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
