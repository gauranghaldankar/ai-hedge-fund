import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Search, Loader2 } from 'lucide-react';
import { screenerApi } from '@/services/screener-service';
import { ScreenerResultRow, WeightProfileName } from './types';
import { WeightValues } from './types';
import { ScreenerScoreBar } from './ScreenerScoreBar';
import { cn } from '@/lib/utils';

interface CustomTickerSearchProps {
  weightProfile: WeightProfileName;
  customWeights: WeightValues;
  onRunFullAnalysis: (ticker: string) => void;
}

export function CustomTickerSearch({ weightProfile, customWeights, onRunFullAnalysis }: CustomTickerSearchProps) {
  const [ticker, setTicker] = useState('');
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<ScreenerResultRow | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleSearch = async () => {
    if (!ticker.trim()) return;
    setLoading(true);
    setError(null);
    setResult(null);

    try {
      const res = await screenerApi.scoreCustomTicker(
        ticker.trim(),
        weightProfile,
        weightProfile === 'custom' ? customWeights : undefined,
      );
      setResult(res);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <div className="relative flex-1">
          <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
          <input
            type="text"
            placeholder="Custom ticker, e.g. SGFIN.NS"
            value={ticker}
            onChange={(e) => setTicker(e.target.value.toUpperCase())}
            onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
            className="w-full h-8 pl-8 pr-3 text-xs bg-background border rounded-md focus:outline-none focus:ring-1 focus:ring-primary"
          />
        </div>
        <Button size="sm" className="h-8 px-3 text-xs" onClick={handleSearch} disabled={loading}>
          {loading ? <Loader2 size={12} className="animate-spin" /> : 'Score'}
        </Button>
      </div>

      {error && (
        <div className="text-xs text-red-400 bg-red-500/10 rounded px-3 py-2">{error}</div>
      )}

      {result && (
        <div className="border rounded-lg p-3 space-y-2 bg-muted/20">
          <div className="flex items-center justify-between">
            <div>
              <span className="text-sm font-bold">{result.ticker}</span>
              {result.company_name && (
                <span className="ml-2 text-xs text-muted-foreground">{result.company_name}</span>
              )}
            </div>
            <span className="text-lg font-bold tabular-nums">
              {(result.composite_score ?? 0).toFixed(1)}
            </span>
          </div>

          <ScreenerScoreBar score={result.composite_score ?? 0} showLabel />

          <div className="grid grid-cols-3 gap-1.5 text-xs">
            {[
              { label: 'Valuation', value: result.valuation_score },
              { label: 'Fundamentals', value: result.fundamentals_score },
              { label: 'Jhunjhunwala', value: result.jhunjhunwala_score },
              { label: 'Growth', value: result.growth_score },
              { label: 'Insider', value: result.insider_score },
              { label: 'Technical', value: result.technical_score },
            ].map(({ label, value }) => (
              <div key={label} className="bg-muted/40 rounded p-1.5">
                <div className="text-muted-foreground">{label}</div>
                <div className="font-medium tabular-nums">{(value ?? 0).toFixed(1)}</div>
              </div>
            ))}
          </div>

          <Button
            size="sm"
            variant="outline"
            className="w-full h-7 text-xs"
            onClick={() => onRunFullAnalysis(result.ticker)}
          >
            Run Full Analysis
          </Button>
        </div>
      )}
    </div>
  );
}
