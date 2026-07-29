import { useEffect, useState } from 'react';
import { cn } from '@/lib/utils';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

interface TickerRow {
  ticker: string;
  action: string;
  confidence: number;
  price_then: number | null;
  price_now: number | null;
  pct_change: number | null;
  consensus: string;
}

interface RunRow {
  run_id: number;
  flow_id: number;
  flow_name: string;
  created_at: string;
  tickers: TickerRow[];
}

function ActionBadge({ action }: { action: string }) {
  const colors: Record<string, string> = {
    buy: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30',
    short: 'bg-red-500/15 text-red-400 border-red-500/30',
    hold: 'bg-zinc-500/10 text-zinc-400 border-zinc-500/20',
    cover: 'bg-blue-500/15 text-blue-400 border-blue-500/30',
    sell: 'bg-orange-500/15 text-orange-400 border-orange-500/30',
  };
  return (
    <span className={cn('px-2 py-0.5 rounded text-xs font-semibold border uppercase', colors[action] ?? colors.hold)}>
      {action}
    </span>
  );
}

function ConsensusDot({ consensus }: { consensus: string }) {
  const colors: Record<string, string> = {
    bullish: 'bg-emerald-400',
    bearish: 'bg-red-400',
    neutral: 'bg-zinc-400',
  };
  return (
    <span className="flex items-center gap-1.5">
      <span className={cn('w-2 h-2 rounded-full inline-block', colors[consensus] ?? 'bg-zinc-400')} />
      <span className="text-xs capitalize text-muted-foreground">{consensus}</span>
    </span>
  );
}

function PctChange({ value }: { value: number | null }) {
  if (value === null) return <span className="text-xs text-muted-foreground">—</span>;
  const positive = value >= 0;
  return (
    <span className={cn('text-sm font-mono font-semibold', positive ? 'text-emerald-400' : 'text-red-400')}>
      {positive ? '+' : ''}{value.toFixed(2)}%
    </span>
  );
}

export function PnLPage() {
  const [runs, setRuns] = useState<RunRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedRuns, setExpandedRuns] = useState<Set<number>>(new Set());

  useEffect(() => {
    setLoading(true);
    fetch(`${API_BASE_URL}/pnl/summary`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((d) => {
        setRuns(d.runs ?? []);
        // Auto-expand first run
        if (d.runs?.length > 0) setExpandedRuns(new Set([d.runs[0].run_id]));
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  const toggleRun = (runId: number) => {
    setExpandedRuns((prev) => {
      const next = new Set(prev);
      next.has(runId) ? next.delete(runId) : next.add(runId);
      return next;
    });
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full text-muted-foreground text-sm">
        Loading P&amp;L history...
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-full text-red-400 text-sm">
        Failed to load: {error}
      </div>
    );
  }

  if (runs.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-3 text-muted-foreground">
        <div className="text-base font-medium">No completed runs yet</div>
        <div className="text-sm">Run a flow to see your P&amp;L history here.</div>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col overflow-hidden bg-background">
      {/* Header */}
      <div className="px-6 py-4 border-b shrink-0">
        <h2 className="text-base font-semibold">P&amp;L History</h2>
        <p className="text-xs text-muted-foreground mt-0.5">
          Price at recommendation vs today — {runs.length} completed run{runs.length !== 1 ? 's' : ''}
        </p>
      </div>

      {/* Run list */}
      <div className="flex-1 overflow-y-auto">
        {runs.map((run) => {
          const expanded = expandedRuns.has(run.run_id);
          const date = new Date(run.created_at).toLocaleString('en-IN', {
            day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit',
          });

          // Summary stats
          const withPrices = run.tickers.filter((t) => t.pct_change !== null);
          const avgChange = withPrices.length
            ? withPrices.reduce((s, t) => s + (t.pct_change ?? 0), 0) / withPrices.length
            : null;
          const bullishCount = run.tickers.filter((t) => t.consensus === 'bullish').length;

          return (
            <div key={run.run_id} className="border-b">
              {/* Run header — clickable to expand */}
              <button
                className="w-full flex items-center gap-4 px-6 py-3 hover:bg-muted/30 transition-colors text-left"
                onClick={() => toggleRun(run.run_id)}
              >
                <span className="text-sm font-medium min-w-32 shrink-0">{run.flow_name}</span>
                <span className="text-xs text-muted-foreground">{date}</span>
                <span className="text-xs text-muted-foreground ml-auto shrink-0">
                  {run.tickers.length} stock{run.tickers.length !== 1 ? 's' : ''}
                  {bullishCount > 0 && ` · ${bullishCount} bullish`}
                </span>
                {avgChange !== null && (
                  <span className={cn(
                    'text-xs font-mono font-semibold ml-2 shrink-0',
                    avgChange >= 0 ? 'text-emerald-400' : 'text-red-400'
                  )}>
                    avg {avgChange >= 0 ? '+' : ''}{avgChange.toFixed(1)}%
                  </span>
                )}
                <span className="text-muted-foreground ml-2 text-xs">{expanded ? '▾' : '▸'}</span>
              </button>

              {/* Expanded ticker rows */}
              {expanded && (
                <div className="px-6 pb-3">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-xs text-muted-foreground border-b">
                        <th className="text-left py-2 font-medium w-32">Ticker</th>
                        <th className="text-left py-2 font-medium w-20">Action</th>
                        <th className="text-right py-2 font-medium w-24">Price then</th>
                        <th className="text-right py-2 font-medium w-24">Price now</th>
                        <th className="text-right py-2 font-medium w-24">Change</th>
                        <th className="text-left py-2 font-medium pl-4 w-28">Consensus</th>
                        <th className="text-right py-2 font-medium w-20">Conf.</th>
                      </tr>
                    </thead>
                    <tbody>
                      {run.tickers.map((t) => (
                        <tr key={t.ticker} className="border-b border-muted/30 hover:bg-muted/10">
                          <td className="py-2 font-mono text-xs font-semibold text-foreground">
                            {t.ticker.replace('.NS', '')}
                            {t.ticker.endsWith('.NS') && (
                              <span className="text-muted-foreground font-normal">.NS</span>
                            )}
                          </td>
                          <td className="py-2"><ActionBadge action={t.action} /></td>
                          <td className="py-2 text-right font-mono text-xs text-muted-foreground">
                            {t.price_then ? `₹${t.price_then.toLocaleString('en-IN')}` : '—'}
                          </td>
                          <td className="py-2 text-right font-mono text-xs">
                            {t.price_now ? `₹${t.price_now.toLocaleString('en-IN')}` : '—'}
                          </td>
                          <td className="py-2 text-right"><PctChange value={t.pct_change} /></td>
                          <td className="py-2 pl-4"><ConsensusDot consensus={t.consensus} /></td>
                          <td className="py-2 text-right text-xs text-muted-foreground">{t.confidence}%</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
