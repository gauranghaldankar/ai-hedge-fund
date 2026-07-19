import { ProgressEvent } from './types';
import { cn } from '@/lib/utils';

interface ScreenerRunProgressProps {
  events: ProgressEvent[];
  total: number;
  done: number;
  isRunning: boolean;
}

export function ScreenerRunProgress({ events, total, done, isRunning }: ScreenerRunProgressProps) {
  const pct = total > 0 ? Math.round((done / total) * 100) : 0;

  const recentEvents = [...events].slice(-5).reverse();

  return (
    <div className="space-y-3 p-4 border rounded-lg bg-muted/20">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium">
          {isRunning ? 'Running Screener...' : 'Screener Complete'}
        </span>
        <span className="text-sm text-muted-foreground tabular-nums">
          {done} / {total} ({pct}%)
        </span>
      </div>

      {/* Progress bar */}
      <div className="h-2 bg-muted rounded-full overflow-hidden">
        <div
          className={cn(
            'h-full rounded-full transition-all duration-300',
            isRunning ? 'bg-primary animate-pulse' : 'bg-emerald-500',
          )}
          style={{ width: `${pct}%` }}
        />
      </div>

      {/* Recent tickers */}
      <div className="space-y-1">
        {recentEvents.map((e, i) => (
          <div key={i} className="flex items-center gap-2 text-xs text-muted-foreground">
            <span
              className={cn(
                'w-1.5 h-1.5 rounded-full shrink-0',
                e.error ? 'bg-red-500' : 'bg-emerald-500',
              )}
            />
            <span className="font-mono">{e.ticker}</span>
            {!e.error && <span className="ml-auto text-foreground font-medium">{e.score.toFixed(1)}</span>}
            {e.error && <span className="ml-auto text-red-400 truncate max-w-32">{e.error}</span>}
          </div>
        ))}
      </div>
    </div>
  );
}
