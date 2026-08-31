export type ValidationStatus =
  | 'missing'
  | 'extracted'
  | 'pending_confirmation'
  | 'confirmed'
  | 'corrected_by_user'
  | 'conflicting'
  | 'not_applicable'
  | 'deferred';

export type Requirement =
  | 'required'
  | 'conditionally_required'
  | 'recommended'
  | 'optional';

export interface CompanyFieldProgress {
  key: string;
  label: string;
  requirement: Requirement;
  status: ValidationStatus;
  applicable: boolean | null;
}

export interface CompanyCompletion {
  percentage: number;
  can_complete: boolean;
  final_approved: boolean;
  required: { completed: number; total: number; remaining: number };
  conditional: {
    completed: number;
    total: number;
    evaluated: number;
    applicable: number;
    remaining: number;
  };
  recommended: { captured: number; total: number };
  optional: { captured: number; total: number };
  blockers: Array<{ field: string; label: string; status: string }>;
}

export interface CompanyProfileResponse {
  id: string;
  company_id: string;
  data: Record<string, unknown>;
  fields: CompanyFieldProgress[];
  completion: CompanyCompletion;
  updated_at: string | null;
}

export interface CompanyMediaAsset {
  id: string; role: string; name: string; mime_type: string; size_bytes: number;
  source_url: string | null; is_primary: boolean; review_status: string;
  image_url: string; created_at: string;
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

export interface ChatAttachment {
  id: string; kind: string; name: string; mime_type: string | null; size_bytes: number | null;
  status: SourceStatus; url: string | null; download_url: string | null;
}

export interface NextQuestion {
  field: string | null; label: string; prompt: string; input_type: string;
  options: string[]; examples: string[]; allow_custom: boolean;
  minimum_words: number | null; minimum_characters?: number | null;
  help_text?: string | null;
  answer_actions?: Record<string, { kind: string; source_field?: string }>;
}

export type SourceKind =
  | 'official_website'
  | 'social_profile'
  | 'online_document'
  | 'third_party'
  | 'uploaded_file';

export type SourceStatus = 'processing' | 'ready' | 'failed';
export type ProposalStatus = 'pending' | 'confirmed' | 'corrected' | 'rejected';

export interface SourceProposal {
  id: string;
  field: string;
  label: string;
  value: unknown;
  evidence: string | null;
  confidence: 'high' | 'medium' | 'low' | null;
  status: ProposalStatus;
  draftValue?: string;
  submitting?: boolean;
  errorMessage?: string;
}

export interface OnboardingSource {
  id: string;
  kind: SourceKind;
  status: SourceStatus;
  name: string;
  url: string | null;
  mime_type: string | null;
  size_bytes: number | null;
  message_id: string | null;
  download_url: string | null;
  error_message: string | null;
  proposals: SourceProposal[];
  created_at: string;
  updated_at: string;
}

export interface ChatTurnResponse {
  request_id?: string | null;
  message_saved: boolean;
  profile_changed: boolean;
  field_update_status: 'accepted' | 'rejected' | 'not_applicable';
  assistant_status: 'deterministic' | 'llm' | 'fallback';
  source_actions: Array<{
    url: string; action: string; status: string; error?: string | null;
  }>;
  message: ChatMessage;
  user_message?: ChatMessage | null;
  profile: CompanyProfileResponse;
  accepted_fields: string[];
  rejected_updates: Array<{ field: string | null; reason: string }>;
  sources: OnboardingSource[];
  next_question: NextQuestion | null;
}

export interface OnboardingState {
  messages: ChatMessage[];
  profile: CompanyProfileResponse;
  sources: OnboardingSource[];
  next_question: NextQuestion | null;
  stage: OnboardingStage;
  version: number;
  team?: TeamOnboarding;
}

export type OnboardingStage =
  | 'website'
  | 'processing'
  | 'website_review'
  | 'logo_review'
  | 'required'
  | 'team'
  | 'conditional'
  | 'enrichment'
  | 'approval'
  | 'complete';

export type TeamRole = 'assistant' | 'mkt' | 'sales';
export type TeamRoleStatus = 'missing' | 'confirmed' | 'deferred' | 'not_applicable';

export interface TeamMember {
  id: string;
  first_name?: string | null;
  last_name?: string | null;
  email: string;
  role: 'admin' | TeamRole;
  is_active: boolean;
}

export interface TeamMemberInvite {
  first_name: string;
  last_name: string;
  email: string;
  role: TeamRole;
  timezone?: string;
  project_access_scope?: 'all' | 'selected';
  project_ids?: string[];
}

export interface TeamProjectOption { id: string; name: string; }

export interface TeamRoleProgress {
  role: TeamRole;
  label: string;
  status: TeamRoleStatus;
  active_users: number;
}

export interface TeamOnboarding {
  administrator: TeamMember | null;
  members: TeamMember[];
  roles: TeamRoleProgress[];
  projects?: TeamProjectOption[];
}

export const EMPTY_TEAM_ONBOARDING: TeamOnboarding = {
  administrator: null,
  members: [],
  roles: [
    { role: 'assistant', label: 'Assistant users', status: 'missing', active_users: 0 },
    { role: 'mkt', label: 'Marketing users', status: 'missing', active_users: 0 },
    { role: 'sales', label: 'Sales users', status: 'missing', active_users: 0 },
  ],
};

export interface ProposalDecisionResponse {
  proposal: SourceProposal;
  profile: CompanyProfileResponse;
}

export const EMPTY_COMPANY_PROFILE: CompanyProfileResponse = {
  id: '',
  company_id: '',
  data: {},
  fields: [],
  completion: {
    percentage: 0,
    can_complete: false,
    final_approved: false,
    required: { completed: 0, total: 10, remaining: 10 },
    conditional: { completed: 0, total: 5, evaluated: 0, applicable: 0, remaining: 0 },
    recommended: { captured: 0, total: 27 },
    optional: { captured: 0, total: 18 },
    blockers: [],
  },
  updated_at: null,
};
