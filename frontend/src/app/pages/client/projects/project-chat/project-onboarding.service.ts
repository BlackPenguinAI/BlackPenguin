import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { API_V1_URL } from '../../../../core/config/api.config';

import {
  Campaign, ChatMessage, ChatTurn, MetaConnection, OnboardingState, ProjectProfile, ProjectSource,
  SourceProposal,
} from './project-onboarding.models';

@Injectable({ providedIn: 'root' })
export class ProjectOnboardingService {
  private readonly baseUrl = `${API_V1_URL}/projects`;
  constructor(private readonly http: HttpClient) {}

  getProfile(id: string): Observable<ProjectProfile> { return this.http.get<ProjectProfile>(`${this.baseUrl}/${id}/profile`); }
  getHistory(id: string): Observable<ChatMessage[]> { return this.http.get<ChatMessage[]>(`${this.baseUrl}/${id}/chat`); }
  startChat(id: string): Observable<ChatTurn> { return this.http.post<ChatTurn>(`${this.baseUrl}/${id}/chat/start`, {}); }
  bootstrap(id: string, initialUrl: string): Observable<ChatTurn> { return this.http.post<ChatTurn>(`${this.baseUrl}/${id}/chat/bootstrap`, { initial_url: initialUrl, skip_website: false }); }
  getState(id: string): Observable<OnboardingState> { return this.http.get<OnboardingState>(`${this.baseUrl}/${id}/chat/state`); }
  complete(id: string): Observable<{ completed: boolean; redirect_url: string; profile: ProjectProfile }> {
    return this.http.post<{ completed: boolean; redirect_url: string; profile: ProjectProfile }>(`${this.baseUrl}/${id}/onboarding/complete`, {});
  }
  sendMessage(id: string, message: string, inReplyToMessageId?: string | null): Observable<ChatTurn> {
    return this.http.post<ChatTurn>(`${this.baseUrl}/${id}/chat`, { message, in_reply_to_message_id: inReplyToMessageId || null });
  }
  sendMessageWithFiles(id: string, message: string, files: File[], inReplyToMessageId?: string | null): Observable<ChatTurn> {
    const body = new FormData();
    body.append('message', message);
    if (inReplyToMessageId) body.append('in_reply_to_message_id', inReplyToMessageId);
    files.forEach((file) => body.append('files', file, file.name));
    return this.http.post<ChatTurn>(`${this.baseUrl}/${id}/chat/with-files`, body);
  }
  getSources(id: string): Observable<ProjectSource[]> { return this.http.get<ProjectSource[]>(`${this.baseUrl}/${id}/sources`); }
  uploadFiles(id: string, files: File[]): Observable<ProjectSource[]> {
    const body = new FormData(); files.forEach((file) => body.append('files', file, file.name));
    return this.http.post<ProjectSource[]>(`${this.baseUrl}/${id}/sources/files`, body);
  }
  downloadAttachment(url: string): Observable<Blob> {
    return this.http.get(url, { responseType: 'blob' });
  }
  decideProposal(id: string, proposalId: string, action: 'confirm' | 'correct' | 'reject', value?: unknown): Observable<{ proposal: SourceProposal; profile: ProjectProfile }> {
    return this.http.post<{ proposal: SourceProposal; profile: ProjectProfile }>(`${this.baseUrl}/${id}/proposals/${proposalId}/decision`, { action, value });
  }
  setCover(id: string, sourceId: string): Observable<ProjectSource> {
    return this.http.post<ProjectSource>(`${this.baseUrl}/${id}/sources/${sourceId}/cover`, {});
  }
  getCampaigns(id: string): Observable<Campaign[]> { return this.http.get<Campaign[]>(`${this.baseUrl}/${id}/campaigns`); }
  createCampaign(id: string, campaign: Partial<Campaign>): Observable<Campaign> { return this.http.post<Campaign>(`${this.baseUrl}/${id}/campaigns`, campaign); }
  getMetaConnections(): Observable<MetaConnection[]> { return this.http.get<MetaConnection[]>(`${this.baseUrl}/integrations/meta/connections`); }
  createMetaConnection(payload: Record<string, unknown>): Observable<MetaConnection> { return this.http.post<MetaConnection>(`${this.baseUrl}/integrations/meta/connections`, payload); }
  verifyMetaConnection(id: string): Observable<MetaConnection> { return this.http.post<MetaConnection>(`${this.baseUrl}/integrations/meta/connections/${id}/verify`, {}); }
}
