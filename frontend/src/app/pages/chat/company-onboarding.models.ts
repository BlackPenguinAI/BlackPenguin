export type ValidationStatus =
  | 'missing'
  | 'extracted'
  | 'pending_confirmation'
  | 'confirmed'
  | 'corrected_by_user'
  | 'conflicting'
  | 'not_applicable';

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

export interface ChatMessage {
  sender: 'user' | 'ai';
  content: string;
  created_at: string | Date;
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
}

export interface OnboardingSource {
  id: string;
  kind: SourceKind;
  status: SourceStatus;
  name: string;
  url: string | null;
  mime_type: string | null;
  size_bytes: number | null;
  error_message: string | null;
  proposals: SourceProposal[];
  created_at: string;
  updated_at: string;
}

export interface ChatTurnResponse {
  message: ChatMessage;
  profile: CompanyProfileResponse;
  accepted_fields: string[];
  rejected_updates: Array<{ field: string | null; reason: string }>;
  sources: OnboardingSource[];
}

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
    required: { completed: 0, total: 11, remaining: 11 },
    conditional: { completed: 0, total: 7, evaluated: 0, applicable: 0, remaining: 0 },
    recommended: { captured: 0, total: 26 },
    optional: { captured: 0, total: 19 },
    blockers: [],
  },
  updated_at: null,
};
