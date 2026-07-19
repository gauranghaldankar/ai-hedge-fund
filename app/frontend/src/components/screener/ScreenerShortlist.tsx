import { cn } from '@/lib/utils';
import { ScreenerResultRow } from './types';
import { computeCompositeClientSide, WeightProfile } from './profiles';
import { WeightValues } from './types';

interface ScreenerShortlistProps {
  results: ScreenerResultRow[];
  activeProfile: WeightProfile | null;
  customWeights: WeightValues;
  onSelectStock: (row: ScreenerResultRow) => void;
}

export function ScreenerShortlist({
  results,
  activeProfile,
  customWeights,
  onSelectStock,
}: ScreenerShortlistProps) {
  const shortlisted = results.filter((r) => r.is_shortlisted);

  if (shortlisted.length === 0) {
    return null;
  }

  const weights = activeProfile?.weights ?? customWeights;

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 mb-3">
        <div className="w-2 h-2 rounded-full bg-emerald-500" />
        <span className="text-sm font-semibold">Shortlisted ({shortlisted.length})</span>
        <span className="text-xs text-muted-foreground">— Score ≥ threshold</span>
      </div>

      <div className="flex flex-wrap gap-2">
        {shortlisted.map((row) => {
          const score = activeProfile
            ? computeCompositeClientSide(row, weights)
            : row.composite_score;

          return (
            <button
              key={row.ticker}
              onClick={() => onSelectStock(row)}
              className={cn(
                'group flex flex-col items-start gap-0.5 px-3 py-2 rounded-lg border',
                'bg-emerald-500/5 border-emerald-500/20',
                'hover:bg-emerald-500/10 hover:border-emerald-500/40 transition-all cursor-pointer',
              )}
            >
              <span className="text-xs font-semibold text-emerald-400">{row.ticker.replace('.NS', '')}</span>
              <span className="text-xs text-muted-foreground truncate max-w-24">{row.company_name}</span>
              <span className="text-sm font-mono font-bold text-emerald-300">{score.toFixed(1)}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
