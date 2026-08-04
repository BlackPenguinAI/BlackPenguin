export type ValidationStatus =
  | 'missing' | 'extracted' | 'pending_confirmation' | 'confirmed'
  | 'corrected_by_user' | 'conflicting' | 'stale' | 'expired' | 'not_applicable';

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
    blockers: Array<{ field: string; label: string; section: string; status: string }>;
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
}
export interface SourceProposal {
  id: string; field: string; label: string; value: unknown; evidence: string | null;
  confidence: string | null; status: 'pending' | 'confirmed' | 'corrected' | 'rejected'; draftValue?: string;
  submitting?: boolean;
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
}
export interface OnboardingState {
  messages: ChatMessage[]; profile: ProjectProfile; sources: ProjectSource[];
  next_question: NextQuestion; stage: 'website' | 'processing' | 'review' | 'conversation' | 'awaiting_confirmation' | 'complete';
  version: number;
}
export interface NextQuestion {
  field: string | null; label: string; prompt: string; input_type: string;
  options: string[]; examples: string[]; allow_custom: boolean; minimum_words: number | null;
}
export interface Campaign {
  id: string; project_id: string; name: string; platform: string; objective: string | null;
  status: string; external_campaign_id: string | null; lead_form_id: string | null;
  audience_notes: string | null; meta_connection_id: string | null; created_at: string; updated_at: string;
}
export interface MetaConnection {
  id: string; label: string; business_account_id: string | null; ad_account_id: string | null;
  page_id: string | null; token_hint: string; scopes: string[]; expires_at: string | null;
  verified_at: string | null; created_at: string;
}

export const EMPTY_PROJECT_PROFILE: ProjectProfile = {
  id: '', project_id: '', data: {}, fields: [], updated_at: null,
  completion: {
    percentage: 0, required_fields_complete: false, ready_for_confirmation: false,
    can_complete: false, final_approved: false,
    completed: 0, total: 0, remaining: 0, sections: [], blockers: [],
    sales_activation_status: 'not_ready', sales_activation_blockers: [],
  },
};
