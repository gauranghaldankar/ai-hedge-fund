import { WeightProfileName, WeightValues } from './types';

export interface WeightProfile {
  name: WeightProfileName;
  label: string;
  description: string;
  weights: WeightValues;
}

export const PROFILES: Record<Exclude<WeightProfileName, 'custom'>, WeightProfile> = {
  medium_long: {
    name: 'medium_long',
    label: 'Medium–Long Term',
    description: '2–5 year hold. Fundamentals-first; technicals excluded.',
    weights: {
      valuation: 30,
      fundamentals: 25,
      jhunjhunwala: 20,
      growth: 15,
      insider: 10,
      technical: 0,
    },
  },
  short_term: {
    name: 'short_term',
    label: 'Short Term',
    description: '< 6 months. Technical momentum weighted most.',
    weights: {
      valuation: 15,
      fundamentals: 20,
      jhunjhunwala: 5,
      growth: 15,
      insider: 10,
      technical: 35,
    },
  },
};

export const SUB_SCORE_LABELS: Record<keyof WeightValues, string> = {
  valuation: 'Valuation',
  fundamentals: 'Fundamentals',
  jhunjhunwala: 'Jhunjhunwala',
  growth: 'Growth',
  insider: 'Insider',
  technical: 'Technical',
};

/**
 * Recompute composite score client-side from stored sub-scores and given weights.
 * This avoids a server round-trip when switching profiles.
 * weights are in percentage (0–100) and must sum to 100.
 */
export function computeCompositeClientSide(
  row: {
    valuation_score: number;
    fundamentals_score: number;
    jhunjhunwala_score: number;
    growth_score: number;
    insider_score: number;
    technical_score: number;
  },
  weights: WeightValues,
): number {
  const total = Object.values(weights).reduce((a, b) => a + b, 0);
  if (total === 0) return 0;
  return (
    (weights.valuation * row.valuation_score +
      weights.fundamentals * row.fundamentals_score +
      weights.jhunjhunwala * row.jhunjhunwala_score +
      weights.growth * row.growth_score +
      weights.insider * row.insider_score +
      weights.technical * row.technical_score) /
    total
  );
}

/** Adjust one slider so total stays at 100 by proportionally scaling the others. */
export function rebalanceWeights(
  current: WeightValues,
  changedKey: keyof WeightValues,
  newValue: number,
): WeightValues {
  const clamped = Math.max(0, Math.min(100, newValue));
  const others = (Object.keys(current) as (keyof WeightValues)[]).filter(k => k !== changedKey);
  const remaining = 100 - clamped;
  const currentOtherSum = others.reduce((s, k) => s + current[k], 0);

  const updated = { ...current, [changedKey]: clamped } as WeightValues;

  if (currentOtherSum === 0) {
    const each = remaining / others.length;
    others.forEach(k => (updated[k] = Math.round(each)));
  } else {
    let distributed = 0;
    others.forEach((k, i) => {
      if (i === others.length - 1) {
        updated[k] = remaining - distributed;
      } else {
        const share = Math.round((current[k] / currentOtherSum) * remaining);
        updated[k] = share;
        distributed += share;
      }
    });
  }

  return updated;
}
