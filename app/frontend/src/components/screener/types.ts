export interface ScreenerRunSummary {
  id: number;
  run_at: string;
  universe: string;
  threshold_mode: ThresholdMode;
  weight_profile: WeightProfileName;
  stocks_screened: number;
  shortlisted_count: number;
  duration_seconds: number | null;
  status: 'IN_PROGRESS' | 'COMPLETE' | 'ERROR';
  source: 'manual' | 'backfill';
  run_date: string | null;
}

export interface ScreenerResultRow {
  id: number;
  run_id: number;
  ticker: string;
  company_name: string;
  industry: string;
  rank: number;
  composite_score: number;
  valuation_score: number;
  fundamentals_score: number;
  jhunjhunwala_score: number;
  growth_score: number;
  insider_score: number;
  technical_score: number;
  is_shortlisted: boolean;
  key_metrics: KeyMetrics;
  scored_at: string | null;
  error: string | null;
}

export interface KeyMetrics {
  pe_ratio: number | null;
  pb_ratio: number | null;
  roe: number | null;
  de_ratio: number | null;
  free_cash_flow: number | null;
  revenue_growth: number | null;
  market_cap: number | null;
  net_margin: number | null;
  operating_margin: number | null;
}

export type ThresholdMode = 'top25' | 'top5pct' | 'score60';
export type WeightProfileName = 'medium_long' | 'short_term' | 'custom';

export interface WeightValues {
  valuation: number;
  fundamentals: number;
  jhunjhunwala: number;
  growth: number;
  insider: number;
  technical: number;
}

export interface ProgressEvent {
  type: 'progress';
  ticker: string;
  done: number;
  total: number;
  score: number;
  error?: string | null;
}

export interface CompleteEvent {
  type: 'complete';
  run_id: number;
  shortlisted: number;
  duration_seconds: number;
  stocks_screened: number;
}

export interface ErrorEvent {
  type: 'error';
  message: string;
}

export type SSEEvent = ProgressEvent | CompleteEvent | ErrorEvent;

export const COLOUR_BANDS = {
  deep_green: { min: 80, label: 'Strong Buy', className: 'text-emerald-400 bg-emerald-400/10' },
  green:      { min: 60, label: 'Watchlist',  className: 'text-green-400 bg-green-400/10' },
  yellow:     { min: 40, label: 'Neutral',    className: 'text-yellow-400 bg-yellow-400/10' },
  red:        { min: 0,  label: 'Screen Out', className: 'text-red-400 bg-red-400/10' },
} as const;

export function getColourBand(score: number): keyof typeof COLOUR_BANDS {
  if (score >= 80) return 'deep_green';
  if (score >= 60) return 'green';
  if (score >= 40) return 'yellow';
  return 'red';
}
