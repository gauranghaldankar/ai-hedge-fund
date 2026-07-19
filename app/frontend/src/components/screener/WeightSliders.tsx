import { WeightValues } from './types';
import { SUB_SCORE_LABELS, rebalanceWeights } from './profiles';

interface WeightSlidersProps {
  weights: WeightValues;
  onChange: (weights: WeightValues) => void;
  disabled?: boolean;
}

export function WeightSliders({ weights, onChange, disabled }: WeightSlidersProps) {
  const total = Object.values(weights).reduce((a, b) => a + b, 0);

  return (
    <div className="space-y-2 p-3 bg-muted/30 rounded-lg">
      <div className="flex items-center justify-between mb-1">
        <span className="text-xs font-medium text-muted-foreground">Custom Weights</span>
        <span className={`text-xs font-mono ${Math.abs(total - 100) > 1 ? 'text-red-400' : 'text-muted-foreground'}`}>
          Total: {total}%
        </span>
      </div>
      {(Object.keys(weights) as (keyof WeightValues)[]).map((key) => (
        <div key={key} className="flex items-center gap-3">
          <span className="text-xs text-muted-foreground w-24 shrink-0">{SUB_SCORE_LABELS[key]}</span>
          <input
            type="range"
            min={0}
            max={100}
            step={5}
            value={weights[key]}
            disabled={disabled}
            onChange={(e) => onChange(rebalanceWeights(weights, key, parseInt(e.target.value)))}
            className="flex-1 h-1.5 accent-primary cursor-pointer disabled:opacity-50"
          />
          <span className="text-xs font-mono text-foreground w-8 text-right">{weights[key]}%</span>
        </div>
      ))}
    </div>
  );
}
