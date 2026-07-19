import { ScreenerResultRow, ThresholdMode } from './types';
import { WeightValues, computeCompositeClientSide } from './profiles';

/**
 * Re-apply shortlist threshold client-side using live weights.
 * Called when the user switches threshold mode or profile without re-running.
 * AC-0109
 */
export function apply_threshold_client(
  results: ScreenerResultRow[],
  mode: ThresholdMode,
  weights: WeightValues,
): ScreenerResultRow[] {
  if (results.length === 0) return results;

  // Recompute composite for each row with current weights
  const scored = results.map((r) => ({
    ...r,
    composite_score: computeCompositeClientSide(r, weights),
  }));

  // Sort desc
  scored.sort((a, b) => b.composite_score - a.composite_score);

  const n = scored.length;
  let cutoff: number;

  if (mode === 'top25') {
    cutoff = 25;
  } else if (mode === 'top5pct') {
    cutoff = Math.max(1, Math.round(n * 0.05));
  } else {
    cutoff = -1; // score60 uses score threshold
  }

  return scored.map((r, i) => ({
    ...r,
    is_shortlisted:
      mode === 'score60' ? r.composite_score >= 60 : i < cutoff,
  }));
}
