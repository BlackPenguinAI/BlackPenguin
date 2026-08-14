export interface ProjectOverviewMetric {
  key: string;
  label: string;
  value: unknown;
  display_value: string;
  status: 'available' | 'pending';
}

export interface ProjectInventorySummary {
  id: string | null;
  typology: string;
  total: number | null;
  sold: number | null;
  available: number | null;
  starting_price: number | null;
  currency: string | null;
  description: string | null; bedrooms: number | null; bathrooms: number | null;
  area_min: number | null; area_max: number | null; area_unit: string | null;
  images_status: string; images: string[];
}

export interface ProjectOverview {
  id: string;
  name: string;
  status: string | null;
  description: string | null;
  address: string | null;
  city: string | null;
  country: string | null;
  delivery_dates: unknown;
  cover_image_url: string | null;
  cover_focal_point: { x: number; y: number };
  metrics: ProjectOverviewMetric[];
  inventory: ProjectInventorySummary[];
  location: { address: string | null; latitude: number | null; longitude: number | null };
  market_intelligence: { report_url: string; total_revenue: number | null; target_roi: number | null; status: string };
  data_completeness: { percentage: number; onboarding_status: string; last_updated_at: string | null };
}

export interface SalesReport {
  inventory_status: string | null;
  total_revenue: number | null;
  target_roi: number | null;
  unit_inventory: Array<{ unit: string; type: string | null; price: number | null; currency: string | null; status: string }>;
  leads_map: Array<{ id: string; name: string; lat: number; lng: number; stage: string }>;
  calculation_status: 'available' | 'pending';
  generated_at: string | null;
}
