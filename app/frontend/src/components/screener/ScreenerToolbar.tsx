import { Button } from '@/components/ui/button';
import { Play, RefreshCw, Loader2, ChevronDown } from 'lucide-react';
import { ScreenerRunSummary, ThresholdMode, WeightProfileName } from './types';
import { WeightProfileSelector } from './WeightProfileSelector';
import { cn } from '@/lib/utils';

interface ScreenerToolbarProps {
  runs: ScreenerRunSummary[];
  activeRunId: number | null;
  isRunning: boolean;
  thresholdMode: ThresholdMode;
  weightProfile: WeightProfileName;
  onRunScreener: () => void;
  onSelectRun: (id: number) => void;
  onThresholdChange: (mode: ThresholdMode) => void;
  onWeightProfileChange: (profile: WeightProfileName) => void;
  onRefreshConstituents: () => void;
  isRefreshing: boolean;
}

const THRESHOLD_OPTIONS: { mode: ThresholdMode; label: string; description: string }[] = [
  { mode: 'top25', label: 'Top 25', description: 'Always highlight the top 25 stocks' },
  { mode: 'top5pct', label: 'Top 5%', description: 'Top 5% of universe (scales with index size)' },
  { mode: 'score60', label: 'Score ≥ 60', description: 'Quality gate: only stocks scoring ≥ 60' },
];

export function ScreenerToolbar({
  runs,
  activeRunId,
  isRunning,
  thresholdMode,
  weightProfile,
  onRunScreener,
  onSelectRun,
  onThresholdChange,
  onWeightProfileChange,
  onRefreshConstituents,
  isRefreshing,
}: ScreenerToolbarProps) {
  const activeRun = runs.find((r) => r.id === activeRunId);

  return (
    <div className="flex items-center gap-3 px-4 py-2 border-b bg-panel shrink-0 flex-wrap">
      {/* Run button */}
      <Button
        size="sm"
        className="h-8 gap-1.5 text-xs"
        onClick={onRunScreener}
        disabled={isRunning}
      >
        {isRunning ? (
          <Loader2 size={12} className="animate-spin" />
        ) : (
          <Play size={12} />
        )}
        {isRunning ? 'Running...' : 'Run Screener'}
      </Button>

      {/* Run history dropdown */}
      {runs.length > 0 && (
        <div className="flex items-center gap-1">
          <span className="text-xs text-muted-foreground">History:</span>
          <select
            value={activeRunId ?? ''}
            onChange={(e) => onSelectRun(Number(e.target.value))}
            className="h-8 px-2 text-xs bg-background border rounded-md focus:outline-none focus:ring-1 focus:ring-primary"
          >
            {runs.map((r) => {
              const dateStr = r.run_date || (r.run_at ? new Date(r.run_at).toLocaleDateString('en-IN', { day: '2-digit', month: 'short' }) : '—');
              return (
                <option key={r.id} value={r.id}>
                  {dateStr} — {r.stocks_screened} stocks, {r.shortlisted_count} shortlisted
                  {r.status === 'ERROR' ? ' ⚠' : ''}
                </option>
              );
            })}
          </select>
        </div>
      )}

      {/* Last run info */}
      {activeRun && (
        <span className="text-xs text-muted-foreground">
          {activeRun.stocks_screened} screened · {activeRun.shortlisted_count} shortlisted
          {activeRun.duration_seconds && ` · ${activeRun.duration_seconds.toFixed(0)}s`}
        </span>
      )}

      <div className="flex-1" />

      {/* Weight profile */}
      <WeightProfileSelector value={weightProfile} onChange={onWeightProfileChange} />

      {/* Threshold mode */}
      <div className="flex items-center gap-1 bg-muted/40 rounded-lg p-1">
        {THRESHOLD_OPTIONS.map((opt) => (
          <button
            key={opt.mode}
            title={opt.description}
            onClick={() => onThresholdChange(opt.mode)}
            className={cn(
              'h-7 px-3 text-xs rounded-md transition-all',
              thresholdMode === opt.mode
                ? 'bg-background shadow-sm text-foreground font-medium'
                : 'text-muted-foreground hover:text-foreground',
            )}
          >
            {opt.label}
          </button>
        ))}
      </div>

      {/* Refresh constituents */}
      <Button
        variant="ghost"
        size="sm"
        className="h-8 w-8 p-0"
        onClick={onRefreshConstituents}
        disabled={isRefreshing}
        title="Refresh Nifty 500 constituent list"
      >
        <RefreshCw size={13} className={cn(isRefreshing && 'animate-spin')} />
      </Button>
    </div>
  );
}
