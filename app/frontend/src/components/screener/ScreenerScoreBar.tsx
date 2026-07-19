import { cn } from '@/lib/utils';
import { getColourBand, COLOUR_BANDS } from './types';

interface ScreenerScoreBarProps {
  score: number;
  showLabel?: boolean;
  className?: string;
}

export function ScreenerScoreBar({ score, showLabel = false, className }: ScreenerScoreBarProps) {
  const band = getColourBand(score);
  const info = COLOUR_BANDS[band];

  const barColour = {
    deep_green: 'bg-emerald-500',
    green: 'bg-green-500',
    yellow: 'bg-yellow-500',
    red: 'bg-red-500',
  }[band];

  return (
    <div className={cn('flex items-center gap-2', className)}>
      <div className="flex-1 h-1.5 bg-muted rounded-full overflow-hidden">
        <div
          className={cn('h-full rounded-full transition-all duration-300', barColour)}
          style={{ width: `${Math.max(0, Math.min(100, score))}%` }}
        />
      </div>
      <span className={cn('text-xs font-medium tabular-nums w-8 text-right', info.className.split(' ')[0])}>
        {score.toFixed(1)}
      </span>
      {showLabel && (
        <span className={cn('text-xs px-1.5 py-0.5 rounded', info.className)}>
          {info.label}
        </span>
      )}
    </div>
  );
}
