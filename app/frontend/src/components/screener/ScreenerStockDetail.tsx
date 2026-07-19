import { Button } from '@/components/ui/button';
import { X } from 'lucide-react';
import { ScreenerResultRow, getColourBand, COLOUR_BANDS } from './types';
import { ScreenerScoreBar } from './ScreenerScoreBar';
import { WeightValues, computeCompositeClientSide, SUB_SCORE_LABELS } from './profiles';
import { cn } from '@/lib/utils';

interface ScreenerStockDetailProps {
  row: ScreenerResultRow;
  weights: WeightValues;
  onClose: () => void;
  onRunFullAnalysis: (ticker: string) => void;
}

function fmt(value: number | null | undefined, pct = false, decimals = 2): string {
  if (value == null) return '—';
  if (pct) return `${(value * 100).toFixed(1)}%`;
  if (Math.abs(value) >= 1e9) return `₹${(value / 1e9).toFixed(1)}B`;
  if (Math.abs(value) >= 1e7) return `₹${(value / 1e7).toFixed(1)}Cr`;
  return value.toFixed(decimals);
}

const SUB_SCORES: { key: keyof ScreenerResultRow; label: string }[] = [
  { key: 'valuation_score', label: 'Valuation' },
  { key: 'fundamentals_score', label: 'Fundamentals' },
  { key: 'jhunjhunwala_score', label: 'Jhunjhunwala' },
  { key: 'growth_score', label: 'Growth' },
  { key: 'insider_score', label: 'Insider' },
  { key: 'technical_score', label: 'Technical' },
];

export function ScreenerStockDetail({ row, weights, onClose, onRunFullAnalysis }: ScreenerStockDetailProps) {
  const composite = computeCompositeClientSide(row, weights);
  const band = getColourBand(composite);
  const bandInfo = COLOUR_BANDS[band];
  const m = row.key_metrics || {};

  return (
    <div className="h-full flex flex-col bg-panel border-l overflow-hidden">
      {/* Header */}
      <div className="flex items-start justify-between p-4 border-b">
        <div>
          <div className="flex items-center gap-2">
            <span className="text-base font-bold">{row.ticker}</span>
            <span className={cn('text-xs px-2 py-0.5 rounded font-medium', bandInfo.className)}>
              {bandInfo.label}
            </span>
          </div>
          <div className="text-xs text-muted-foreground mt-0.5">{row.company_name}</div>
          <div className="text-xs text-muted-foreground">{row.industry}</div>
        </div>
        <Button variant="ghost" size="sm" className="h-7 w-7 p-0" onClick={onClose}>
          <X size={14} />
        </Button>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-5">
        {/* Composite score */}
        <div>
          <div className="flex items-center justify-between mb-1">
            <span className="text-xs text-muted-foreground font-medium">Composite Score</span>
            <span className="text-2xl font-bold tabular-nums">{composite.toFixed(1)}</span>
          </div>
          <ScreenerScoreBar score={composite} />
        </div>

        {/* Sub-score breakdown */}
        <div className="space-y-2">
          <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
            Sub-Score Breakdown
          </span>
          {SUB_SCORES.map(({ key, label }) => {
            const subScore = row[key] as number ?? 0;
            const wKey = label.toLowerCase() as keyof WeightValues;
            const weight = weights[wKey] ?? 0;
            return (
              <div key={key} className="space-y-0.5">
                <div className="flex items-center justify-between text-xs">
                  <span className="text-muted-foreground">{label}</span>
                  <span className="text-muted-foreground">{weight}% weight</span>
                </div>
                <ScreenerScoreBar score={subScore} />
              </div>
            );
          })}
        </div>

        {/* Key metrics card */}
        <div className="space-y-2">
          <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
            Key Metrics
          </span>
          <div className="grid grid-cols-2 gap-2">
            {[
              { label: 'P/E Ratio', value: fmt(m.pe_ratio, false, 1) },
              { label: 'P/B Ratio', value: fmt(m.pb_ratio, false, 2) },
              { label: 'ROE', value: fmt(m.roe, true) },
              { label: 'D/E Ratio', value: fmt(m.de_ratio, false, 2) },
              { label: 'Free Cash Flow', value: fmt(m.free_cash_flow) },
              { label: 'Revenue Growth', value: fmt(m.revenue_growth, true) },
              { label: 'Market Cap', value: fmt(m.market_cap) },
              { label: 'Net Margin', value: fmt(m.net_margin, true) },
            ].map(({ label, value }) => (
              <div key={label} className="bg-muted/30 rounded-md p-2">
                <div className="text-xs text-muted-foreground">{label}</div>
                <div className="text-sm font-medium tabular-nums mt-0.5">{value}</div>
              </div>
            ))}
          </div>
        </div>

        {row.error && (
          <div className="text-xs text-red-400 bg-red-500/10 rounded p-2">
            Scoring error: {row.error}
          </div>
        )}
      </div>

      {/* Footer — Run Full Analysis */}
      <div className="p-4 border-t">
        <Button
          className="w-full"
          size="sm"
          onClick={() => onRunFullAnalysis(row.ticker)}
        >
          Run Full Analysis
        </Button>
        <p className="text-xs text-muted-foreground text-center mt-2">
          Triggers LLM pipeline for {row.ticker}
        </p>
      </div>
    </div>
  );
}
