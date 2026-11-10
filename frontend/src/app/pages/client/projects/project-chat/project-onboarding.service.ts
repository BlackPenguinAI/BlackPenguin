import { MaterialCoverage, MaterialTarget } from './project-onboarding.models';
import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { API_V1_URL } from '../../../../core/config/api.config';

import {
  Campaign, ChatMessage, ChatTurn, MetaAssetDiscovery, MetaAuthorization, MetaConnection, MetaSetupConfiguration, MetaSetupResult, MetaSetupState,
  OnboardingState, ProjectAssignment, ProjectOnboardingActionPayload, ProjectProfile,
  ProjectSalesCandidate, ProjectSource, SourceProposal, ProjectPropertyType, ProjectPropertyTypePayload, PropertyTypeCatalog,
  ProjectFileIntent, ProjectSalesAsset, SalesAssetType,
} from './project-onboarding.models';

@Injectable({ providedIn: 'root' })
export class ProjectOnboardingService {
  private readonly baseUrl = `${API_V1_URL}/projects`;
  constructor(private readonly http: HttpClient) {}
  deferSelection(entityId:string, field:string, questionId:string, values:string[]):Observable<{deferrals:Record<string,any>}> {
    return this.http.post<{deferrals:Record<string,any>}>(`${API_V1_URL}/onboarding-deferrals/project/${entityId}`,
      {card:'field:'+field,question_message_id:questionId,draft:{selected_values:values}});
  }

  saveDetails(id:string,payload:Record<string,unknown>):Observable<ChatTurn>{return this.http.post<ChatTurn>(`${this.baseUrl}/${id}/details`,payload);}
  getProfile(id: string): Observable<ProjectProfile> { return this.http.get<ProjectProfile>(`${this.baseUrl}/${id}/profile`); }
  openEditorTask(id:string,task:string,clientId:string,transition?:Record<string,unknown>):Observable<ChatTurn>{return this.http.post<ChatTurn>(`${this.baseUrl}/${id}/editor/${task}`,{message:'Open review: '+task,client_message_id:clientId,...(transition?{transition}:{})});}
  getHistory(id: string): Observable<ChatMessage[]> { return this.http.get<ChatMessage[]>(`${this.baseUrl}/${id}/chat`); }
  startChat(id: string): Observable<ChatTurn> { return this.http.post<ChatTurn>(`${this.baseUrl}/${id}/chat/start`, {}); }
  bootstrap(id: string, initialUrl: string): Observable<ChatTurn> { return this.http.post<ChatTurn>(`${this.baseUrl}/${id}/chat/bootstrap`, { initial_url: initialUrl, skip_website: false }); }
  getState(id: string): Observable<OnboardingState> { return this.http.get<OnboardingState>(`${this.baseUrl}/${id}/chat/state`); }
  complete(id: string, expectedRevision?: number): Observable<{ completed: boolean; redirect_url: string; profile: ProjectProfile }> {
    return this.http.post<{ completed: boolean; redirect_url: string; profile: ProjectProfile }>(`${this.baseUrl}/${id}/onboarding/complete`, expectedRevision === undefined ? {} : { expected_revision: expectedRevision });
  }
  sendMessage(id: string, message: string, inReplyToMessageId: string | null, clientMessageId: string, selectedValues?: string[]): Observable<ChatTurn> {
    return this.http.post<ChatTurn>(`${this.baseUrl}/${id}/chat`, {
      message, in_reply_to_message_id: inReplyToMessageId || null, client_message_id: clientMessageId,
      ...(selectedValues !== undefined ? {selected_values: selectedValues} : {}),
    });
  }
  sendMessageWithFiles(id: string, message: string, files: File[], intents: ProjectFileIntent[], inReplyToMessageId: string | null, clientMessageId: string): Observable<ChatTurn> {
    const body = new FormData();
    body.append('message', message);
    if (inReplyToMessageId) body.append('in_reply_to_message_id', inReplyToMessageId);
    body.append('client_message_id', clientMessageId);
    body.append('file_intents', JSON.stringify(intents));
    files.forEach((file) => body.append('files', file, file.name));
    return this.http.post<ChatTurn>(`${this.baseUrl}/${id}/chat/with-files`, body);
  }
  patchProfile(id: string, updates: Array<Record<string, unknown>>, expectedRevision?: number): Observable<ProjectProfile> {
    return this.http.patch<ProjectProfile>(`${this.baseUrl}/${id}/profile`, { updates, ...(expectedRevision !== undefined ? { expected_revision: expectedRevision } : {}) });
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
  reviseProposal(id: string, proposalId: string, value: unknown, expectedRevision?: number): Observable<{ proposal: SourceProposal; profile: ProjectProfile }> {
    return this.http.post<{ proposal: SourceProposal; profile: ProjectProfile }>(`${this.baseUrl}/${id}/proposals/${proposalId}/revision`, { value, expected_revision: expectedRevision });
  }
  setCover(id: string, sourceId: string): Observable<ProjectSource> {
    return this.http.post<ProjectSource>(`${this.baseUrl}/${id}/sources/${sourceId}/cover`, {});
  }
  uploadCover(id: string, file: File): Observable<ProjectSource> {
    const body = new FormData(); body.append('file', file, file.name);
    return this.http.post<ProjectSource>(`${this.baseUrl}/${id}/sources/cover-upload`, body);
  }
  uploadPropertyImage(id:string,file:File,sharingIntent:string,tags:SalesAssetType[]):Observable<ProjectSource> {
    const body=new FormData();body.append('file',file,file.name);body.append('sharing_intent',sharingIntent);body.append('content_tags',JSON.stringify(tags));
    return this.http.post<ProjectSource>(`${this.baseUrl}/${id}/sources/image-upload`,body);
  }
  removePropertyImage(id: string, propertyId: string, sourceId: string): Observable<ProjectPropertyType> {
    return this.http.delete<ProjectPropertyType>(`${this.baseUrl}/${id}/property-types/${propertyId}/media/${sourceId}`);
  }
  savePropertyGallery(id: string, propertyId: string, accessible: boolean, sourceIds: string[]): Observable<ProjectSalesAsset | null> {
    return this.http.post<ProjectSalesAsset | null>(`${this.baseUrl}/${id}/property-types/${propertyId}/gallery`, {accessible_to_leads: accessible, source_ids: sourceIds});
  }
  uploadPropertyDocument(id: string, propertyId: string, file: File, accessible: boolean, tags: SalesAssetType[]): Observable<ProjectSalesAsset> {
    const body = new FormData(); body.append('file', file, file.name); body.append('accessible_to_leads', String(accessible)); body.append('content_tags', JSON.stringify(tags));
    return this.http.post<ProjectSalesAsset>(`${this.baseUrl}/${id}/property-types/${propertyId}/documents`, body);
  }
  removePropertyDocument(id: string, propertyId: string, assetId: string): Observable<void> {
    return this.http.delete<void>(`${this.baseUrl}/${id}/property-types/${propertyId}/documents/${assetId}`);
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
  getSalesAssets(id: string): Observable<ProjectSalesAsset[]> {
    return this.http.get<ProjectSalesAsset[]>(`${this.baseUrl}/${id}/sales-assets?include_archived=true`);
  }
  createSalesAsset(id: string, payload: {
    source_id: string; property_type_id: string | null; asset_type: SalesAssetType;
    content_tags?: SalesAssetType[];
    display_name: string; description: string | null; valid_from: string | null;
    valid_until: string | null; allowed_channels: Array<'sms' | 'whatsapp'>;
  }): Observable<ProjectSalesAsset> {
    return this.http.post<ProjectSalesAsset>(`${this.baseUrl}/${id}/sales-assets`, payload);
  }
  getMaterialTargets(id: string): Observable<MaterialTarget[]> {
    return this.http.get<MaterialTarget[]>(`${this.baseUrl}/${id}/material-targets`);
  }
  updateSalesAsset(id: string, assetId: string, payload: Pick<ProjectSalesAsset, 'property_type_id'|'asset_type'|'content_tags'|'display_name'|'description'|'valid_from'|'valid_until'|'allowed_channels'> & {coverage?: MaterialCoverage[] | null}): Observable<ProjectSalesAsset> {
    return this.http.put<ProjectSalesAsset>(`${this.baseUrl}/${id}/sales-assets/${assetId}`,payload);
  }
  approveSalesAsset(id: string, assetId: string): Observable<ProjectSalesAsset> {
    return this.http.post<ProjectSalesAsset>(`${this.baseUrl}/${id}/sales-assets/${assetId}/approve`, {});
  }
  archiveSalesAsset(id: string, assetId: string): Observable<void> {
    return this.http.delete<void>(`${this.baseUrl}/${id}/sales-assets/${assetId}`);
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
      routing_weight: 100, accepts_new_leads: true, sales_enabled: true, is_active: true,
    });
  }
  inviteAndAssignSalesUser(id: string, payload: { first_name: string; last_name: string; email: string }): Observable<ProjectAssignment> {
    return this.http.post<ProjectAssignment>(`${this.baseUrl}/${id}/team/invite-sales`, payload);
  }
  getMetaSetupConfiguration(id: string): Observable<MetaSetupConfiguration> {
    return this.http.get<MetaSetupConfiguration>(`${this.baseUrl}/${id}/meta-setup/config`);
  }
  startMetaOAuth(id: string): Observable<{ authorization_url: string; expires_at: string; state: string }> {
    return this.http.get<{ authorization_url: string; expires_at: string; state: string }>(`${this.baseUrl}/${id}/meta/oauth/start`);
  }
  getMetaSetupState(id: string): Observable<MetaSetupState> {
    return this.http.get<MetaSetupState>(`${this.baseUrl}/${id}/meta/setup-state`);
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
