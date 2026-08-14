export type ValidationStatus =
  | 'missing' | 'extracted' | 'pending_confirmation' | 'confirmed'
  | 'corrected_by_user' | 'conflicting' | 'stale' | 'expired' | 'not_applicable' | 'deferred';

export interface ProjectFieldProgress {
  key: string;
  label: string;
  section: string;
  requirement: string;
  status: ValidationStatus;
  applicable: boolean | null;
}

export interface SectionProgress {
  key: string;
  label: string;
  completed: number;
  total: number;
  percentage: number;
}

export interface ProjectProfile {
  id: string;
  project_id: string;
  project_name: string;
  data: Record<string, unknown>;
  fields: ProjectFieldProgress[];
  completion: {
    percentage: number;
    required_fields_complete: boolean;
    ready_for_confirmation: boolean;
    can_complete: boolean;
    final_approved: boolean;
    completed: number;
    total: number;
    remaining: number;
    sections: SectionProgress[];
    blockers: Array<{ field: string; label: string; section: string; requirement: string; status: string }>;
    sales_activation_status: 'ready' | 'not_ready';
    sales_activation_blockers: Array<{ field: string; label: string; section: string; status: string }>;
  };
  updated_at: string | null;
}

export interface ChatAttachment {
  id: string;
  kind: string;
  name: string;
  mime_type: string | null;
  size_bytes: number | null;
  status: 'processing' | 'ready' | 'failed';
  url: string | null;
  download_url: string | null;
}
export interface ChatMessage {
  id?: string;
  sender: 'user' | 'ai';
  content: string;
  created_at: string | Date;
  attachments: ChatAttachment[];
  ui_payload?: NextQuestion | null;
  response_payload?: { status: string; answer: string; selected_option?: string | null; custom?: boolean } | null;
  in_reply_to_message_id?: string | null;
}
export interface SourceProposal {
  id: string; field: string; label: string; value: unknown; evidence: string | null;
  confidence: string | null; status: 'pending' | 'confirmed' | 'corrected' | 'rejected'; draftValue?: string;
  submitting?: boolean; inlineError?: string;
  validation?: {
    code: string; field: string; message: string;
    minimum_words?: number; minimum_characters?: number;
  } | null;
}
export interface ProjectSource {
  id: string; kind: string; status: 'processing' | 'ready' | 'failed'; name: string;
  url: string | null; mime_type: string | null; size_bytes: number | null; error_message: string | null;
  message_id: string | null; download_url: string | null;
  is_primary: boolean;
  proposals: SourceProposal[]; created_at: string; updated_at: string;
}
export interface ChatTurn {
  message: ChatMessage; user_message: ChatMessage | null; profile: ProjectProfile; accepted_fields: string[];
  rejected_updates: Array<{ field: string | null; reason: string }>; sources: ProjectSource[];
  next_question: NextQuestion;
  request_id?: string | null; message_saved?: boolean; profile_changed?: boolean;
  field_update_status?: 'accepted' | 'rejected' | 'not_applicable';
  assistant_status?: 'deterministic' | 'llm' | 'fallback'; redirect_url?: string | null;
}
export interface OnboardingState {
  messages: ChatMessage[]; profile: ProjectProfile; sources: ProjectSource[];
  next_question: NextQuestion; stage: 'website' | 'processing' | 'review' | 'conversation' | 'awaiting_confirmation' | 'complete';
  version: number;
}
export interface NextQuestion {
  field: string | null; label: string; prompt: string; input_type: string;
  options: string[]; examples: string[]; allow_custom: boolean; minimum_words: number | null;
  minimum_characters?: number | null; help_text?: string | null;
  answer_actions?: Record<string, { kind: string; [key: string]: unknown }>;
}
export interface Campaign {
  id: string; project_id: string; name: string; platform: string; objective: string | null;
  status: string; external_campaign_id: string | null; lead_form_id: string | null;
  audience_notes: string | null; meta_connection_id: string | null; created_at: string; updated_at: string;
}

export interface PropertyTypeMedia {
  id: string; source_id: string; caption: string | null; sort_order: number; image_url: string;
}

export interface ProjectPropertyType {
  id: string; project_id: string; name: string; code: string | null; description: string | null;
  bedrooms: number | null; bathrooms: number | null; area_min: number | null; area_max: number | null;
  area_unit: string | null; total_units: number | null; available_units: number | null;
  starting_price: number | null; maximum_price: number | null; currency: string | null;
  features: string[]; inventory_updated_at: string | null; images_status: 'pending' | 'provided' | 'deferred';
  review_status: 'candidate' | 'confirmed' | 'rejected'; source_reference: string | null;
  sort_order: number; is_complete: boolean; media: PropertyTypeMedia[]; created_at: string; updated_at: string;
}

export interface PropertyTypeCatalog {
  items: ProjectPropertyType[]; confirmed_count: number; candidate_count: number;
  limit: number; remaining: number; catalog_complete: boolean;
}
export interface MetaConnection {
  id: string; label: string; business_account_id: string | null; ad_account_id: string | null;
  page_id: string | null; token_hint: string; scopes: string[]; expires_at: string | null;
  verified_at: string | null; simulated_verified_at?: string | null;
  verification_mode?: 'simulated' | 'real'; verification_status?: 'pending' | 'running' | 'succeeded' | 'failed';
  created_at: string;
}

export interface ProjectAssignment {
  id: string; project_id: string; user_id: string; responsibility: 'marketing' | 'sales';
  is_primary: boolean; routing_weight: number; accepts_new_leads: boolean; is_active: boolean;
  email: string; first_name: string | null; last_name: string | null;
}

export interface ProjectSalesCandidate {
  id: string; email: string; first_name?: string; last_name?: string;
  role: 'sales'; is_active: boolean;
}

export interface MetaSetupConfiguration {
  partner_business_manager_id: string | null;
  configured: boolean;
}

export interface MetaSetupResult {
  connection: MetaConnection; campaign: Campaign; simulated: true; success: boolean;
  message: string; partner_business_manager_id: string | null;
}

export type ProjectOnboardingAction =
  | 'authorize_ai_sales'
  | 'complete_sales_team'
  | 'defer_sales_team'
  | 'complete_meta_setup'
  | 'defer_meta_setup';

export interface ProjectOnboardingActionPayload {
  action: ProjectOnboardingAction;
  question_message_id: string;
  client_action_id: string;
  page_id?: string;
  ad_account_id?: string;
  lead_form_id?: string;
  page_access_confirmed?: boolean;
  ad_account_access_confirmed?: boolean;
  leads_access_confirmed?: boolean;
}

export const EMPTY_PROJECT_PROFILE: ProjectProfile = {
  id: '', project_id: '', project_name: 'Untitled Project', data: {}, fields: [], updated_at: null,
  completion: {
    percentage: 0, required_fields_complete: false, ready_for_confirmation: false,
    can_complete: false, final_approved: false,
    completed: 0, total: 0, remaining: 0, sections: [], blockers: [],
    sales_activation_status: 'not_ready', sales_activation_blockers: [],
  },
};
