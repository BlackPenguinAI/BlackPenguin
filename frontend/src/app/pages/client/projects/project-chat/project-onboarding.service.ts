import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { API_V1_URL } from '../../../../core/config/api.config';

import {
  Campaign, ChatMessage, ChatTurn, MetaAssetDiscovery, MetaAuthorization, MetaConnection, MetaSetupConfiguration, MetaSetupResult,
  OnboardingState, ProjectAssignment, ProjectOnboardingActionPayload, ProjectProfile,
  ProjectSalesCandidate, ProjectSource, SourceProposal, ProjectPropertyType, ProjectPropertyTypePayload, PropertyTypeCatalog,
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
  sendMessage(id: string, message: string, inReplyToMessageId: string | null, clientMessageId: string): Observable<ChatTurn> {
    return this.http.post<ChatTurn>(`${this.baseUrl}/${id}/chat`, {
      message, in_reply_to_message_id: inReplyToMessageId || null, client_message_id: clientMessageId,
    });
  }
  sendMessageWithFiles(id: string, message: string, files: File[], inReplyToMessageId: string | null, clientMessageId: string): Observable<ChatTurn> {
    const body = new FormData();
    body.append('message', message);
    if (inReplyToMessageId) body.append('in_reply_to_message_id', inReplyToMessageId);
    body.append('client_message_id', clientMessageId);
    files.forEach((file) => body.append('files', file, file.name));
    return this.http.post<ChatTurn>(`${this.baseUrl}/${id}/chat/with-files`, body);
  }
  getSources(id: string): Observable<ProjectSource[]> { return this.http.get<ProjectSource[]>(`${this.baseUrl}/${id}/sources`); }
  retrySource(id: string, sourceId: string): Observable<ProjectSource> {
    return this.http.post<ProjectSource>(`${this.baseUrl}/${id}/sources/${sourceId}/retry`, {});
  }
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
  uploadCover(id: string, file: File): Observable<ProjectSource> {
    const body = new FormData(); body.append('file', file, file.name);
    return this.http.post<ProjectSource>(`${this.baseUrl}/${id}/sources/cover-upload`, body);
  }
  getPropertyTypes(id: string): Observable<PropertyTypeCatalog> {
    return this.http.get<PropertyTypeCatalog>(`${this.baseUrl}/${id}/property-types`);
  }
  confirmPropertyTypeCatalog(id: string): Observable<PropertyTypeCatalog> {
    return this.http.post<PropertyTypeCatalog>(`${this.baseUrl}/${id}/property-types/confirm`, {});
  }
  createPropertyType(id: string, payload: ProjectPropertyTypePayload): Observable<ProjectPropertyType> {
    return this.http.post<ProjectPropertyType>(`${this.baseUrl}/${id}/property-types`, payload);
  }
  updatePropertyType(id: string, propertyTypeId: string, payload: ProjectPropertyTypePayload): Observable<ProjectPropertyType> {
    return this.http.put<ProjectPropertyType>(`${this.baseUrl}/${id}/property-types/${propertyTypeId}`, payload);
  }
  deletePropertyType(id: string, propertyTypeId: string): Observable<void> {
    return this.http.delete<void>(`${this.baseUrl}/${id}/property-types/${propertyTypeId}`);
  }
  attachPropertyTypeMedia(id: string, propertyTypeId: string, sourceIds: string[]): Observable<ProjectPropertyType> {
    return this.http.post<ProjectPropertyType>(`${this.baseUrl}/${id}/property-types/${propertyTypeId}/media`, { source_ids: sourceIds });
  }
  deferPropertyTypeImages(id: string, propertyTypeId: string): Observable<ProjectPropertyType> {
    return this.http.post<ProjectPropertyType>(`${this.baseUrl}/${id}/property-types/${propertyTypeId}/defer-images`, {});
  }
  getCampaigns(id: string): Observable<Campaign[]> { return this.http.get<Campaign[]>(`${this.baseUrl}/${id}/campaigns`); }
  createCampaign(id: string, campaign: Partial<Campaign>): Observable<Campaign> { return this.http.post<Campaign>(`${this.baseUrl}/${id}/campaigns`, campaign); }
  getMetaConnections(): Observable<MetaConnection[]> { return this.http.get<MetaConnection[]>(`${this.baseUrl}/integrations/meta/connections`); }
  createMetaConnection(payload: Record<string, unknown>): Observable<MetaConnection> { return this.http.post<MetaConnection>(`${this.baseUrl}/integrations/meta/connections`, payload); }
  verifyMetaConnection(id: string): Observable<MetaConnection> { return this.http.post<MetaConnection>(`${this.baseUrl}/integrations/meta/connections/${id}/verify`, {}); }
  getProjectTeam(id: string): Observable<ProjectAssignment[]> { return this.http.get<ProjectAssignment[]>(`${this.baseUrl}/${id}/team`); }
  getSalesCandidates(id: string): Observable<ProjectSalesCandidate[]> { return this.http.get<ProjectSalesCandidate[]>(`${this.baseUrl}/${id}/team/candidates`); }
  assignSalesUser(id: string, userId: string): Observable<ProjectAssignment> {
    return this.http.put<ProjectAssignment>(`${this.baseUrl}/${id}/team/${userId}`, {
      user_id: userId, responsibility: 'sales', is_primary: false,
      routing_weight: 100, accepts_new_leads: true, is_active: true,
    });
  }
  inviteAndAssignSalesUser(id: string, payload: { first_name: string; last_name: string; email: string }): Observable<ProjectAssignment> {
    return this.http.post<ProjectAssignment>(`${this.baseUrl}/${id}/team/invite-sales`, payload);
  }
  getMetaSetupConfiguration(id: string): Observable<MetaSetupConfiguration> {
    return this.http.get<MetaSetupConfiguration>(`${this.baseUrl}/${id}/meta-setup/config`);
  }
  startMetaOAuth(id: string): Observable<{ authorization_url: string; expires_at: string }> {
    return this.http.get<{ authorization_url: string; expires_at: string }>(`${this.baseUrl}/${id}/meta/oauth/start`);
  }
  getMetaAuthorizations(id: string): Observable<MetaAuthorization[]> {
    return this.http.get<MetaAuthorization[]>(`${this.baseUrl}/${id}/meta/oauth/authorizations`);
  }
  discoverMetaAssets(id: string, authorizationId: string, pageId = '', adAccountId = ''): Observable<MetaAssetDiscovery> {
    const params: Record<string, string> = { authorization_id: authorizationId };
    if (pageId) params['page_id'] = pageId;
    if (adAccountId) params['ad_account_id'] = adAccountId;
    return this.http.get<MetaAssetDiscovery>(`${this.baseUrl}/${id}/meta/oauth/assets`, { params });
  }
  simulateMetaSetup(id: string, payload: Record<string, unknown>): Observable<MetaSetupResult> {
    return this.http.post<MetaSetupResult>(`${this.baseUrl}/${id}/meta-setup/simulate`, payload);
  }
  applyOnboardingAction(id: string, payload: ProjectOnboardingActionPayload): Observable<ChatTurn> {
    return this.http.post<ChatTurn>(`${this.baseUrl}/${id}/onboarding/actions`, payload);
  }
}
