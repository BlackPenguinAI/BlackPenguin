export interface CompanyOverview {
  company_id: string;
  name: string;
  legal_name: string | null;
  description: string | null;
  headquarters: string | null;
  business_model: unknown;
  asset_classes: unknown;
  operating_footprint: unknown;
  public_contacts: { emails: string[]; phones: string[]; social_profiles: string[] };
  logo_url: string | null;
  metrics: {
    active_projects: number; demo_projects: number;
    campaigns_total: number; campaigns_active: number;
    leads_total: number; leads_current_month: number;
    team_total: number; team_active: number; team_by_role: Record<string, number>;
  };
  completion: { percentage: number; can_complete: boolean; final_approved: boolean };
  updated_at: string | null;
}
