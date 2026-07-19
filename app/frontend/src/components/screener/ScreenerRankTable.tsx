import { useState, useMemo } from 'react';
import { ChevronUp, ChevronDown } from 'lucide-react';
import { cn } from '@/lib/utils';
import { ScreenerResultRow, getColourBand, COLOUR_BANDS } from './types';
import { WeightValues, computeCompositeClientSide } from './profiles';
import { ScreenerScoreBar } from './ScreenerScoreBar';

type SortKey = 'rank' | 'ticker' | 'composite_score' | 'valuation_score' | 'fundamentals_score' | 'jhunjhunwala_score' | 'growth_score' | 'insider_score' | 'technical_score';

interface ScreenerRankTableProps {
  results: ScreenerResultRow[];
  weights: WeightValues;
  prevResults?: ScreenerResultRow[];
  onSelectRow: (row: ScreenerResultRow) => void;
  selectedTicker?: string;
}

export function ScreenerRankTable({ results, weights, prevResults, onSelectRow, selectedTicker }: ScreenerRankTableProps) {
  const [sortKey, setSortKey] = useState<SortKey>('rank');
  const [sortAsc, setSortAsc] = useState(true);
  const [sectorFilter, setSectorFilter] = useState('');
  const [search, setSearch] = useState('');

  // Build prev composite map for delta badges (AC-0114)
  const prevMap = useMemo(() => {
    if (!prevResults) return new Map<string, number>();
    return new Map(prevResults.map((r) => [r.ticker, computeCompositeClientSide(r, weights)]));
  }, [prevResults, weights]);

  // Recompute composite using current weights
  const enriched = useMemo(() => {
    return results.map((r) => ({
      ...r,
      _composite: computeCompositeClientSide(r, weights),
    }));
  }, [results, weights]);

  // Unique sectors for filter dropdown
  const sectors = useMemo(() => {
    const s = new Set(enriched.map((r) => r.industry).filter(Boolean));
    return Array.from(s).sort();
  }, [enriched]);

  // Filter + sort
  const rows = useMemo(() => {
    let filtered = enriched;

    if (sectorFilter) {
      filtered = filtered.filter((r) => r.industry === sectorFilter);
    }
    if (search) {
      const q = search.toLowerCase();
      filtered = filtered.filter(
        (r) => r.ticker.toLowerCase().includes(q) || r.company_name.toLowerCase().includes(q),
      );
    }

    return [...filtered].sort((a, b) => {
      const aVal = sortKey === 'composite_score' ? a._composite : (a[sortKey] as number ?? 0);
      const bVal = sortKey === 'composite_score' ? b._composite : (b[sortKey] as number ?? 0);
      if (typeof aVal === 'string') {
        return sortAsc ? aVal.localeCompare(bVal as string) : (bVal as string).localeCompare(aVal);
      }
      return sortAsc ? aVal - bVal : bVal - aVal;
    });
  }, [enriched, sortKey, sortAsc, sectorFilter, search]);

  const handleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortAsc((p) => !p);
    } else {
      setSortKey(key);
      setSortAsc(false); // desc by default for scores
    }
  };

  const SortIcon = ({ col }: { col: SortKey }) =>
    sortKey === col ? (
      sortAsc ? <ChevronUp size={12} className="inline" /> : <ChevronDown size={12} className="inline" />
    ) : null;

  const ColHeader = ({ col, label, className }: { col: SortKey; label: string; className?: string }) => (
    <th
      className={cn('px-3 py-2 text-left text-xs font-medium text-muted-foreground cursor-pointer hover:text-foreground select-none whitespace-nowrap', className)}
      onClick={() => handleSort(col)}
    >
      {label} <SortIcon col={col} />
    </th>
  );

  return (
    <div className="flex flex-col h-full">
      {/* Filters */}
      <div className="flex items-center gap-2 px-3 py-2 border-b bg-muted/20 shrink-0">
        <input
          type="text"
          placeholder="Search ticker or company..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="flex-1 h-7 px-3 text-xs bg-background border rounded-md focus:outline-none focus:ring-1 focus:ring-primary"
        />
        <select
          value={sectorFilter}
          onChange={(e) => setSectorFilter(e.target.value)}
          className="h-7 px-2 text-xs bg-background border rounded-md focus:outline-none focus:ring-1 focus:ring-primary"
        >
          <option value="">All Sectors</option>
          {sectors.map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
        <span className="text-xs text-muted-foreground whitespace-nowrap">{rows.length} stocks</span>
      </div>

      {/* Table */}
      <div className="flex-1 overflow-auto">
        <table className="w-full text-xs border-collapse">
          <thead className="sticky top-0 bg-panel border-b z-10">
            <tr>
              <ColHeader col="rank" label="#" className="w-10" />
              <ColHeader col="ticker" label="Ticker" />
              <th className="px-3 py-2 text-left text-xs font-medium text-muted-foreground">Sector</th>
              <ColHeader col="composite_score" label="Score" className="w-24" />
              <ColHeader col="valuation_score" label="Val" className="w-16" />
              <ColHeader col="fundamentals_score" label="Fund" className="w-16" />
              <ColHeader col="jhunjhunwala_score" label="JJ" className="w-16" />
              <ColHeader col="growth_score" label="Growth" className="w-16" />
              <ColHeader col="insider_score" label="Insider" className="w-16" />
              <ColHeader col="technical_score" label="Tech" className="w-16" />
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const band = getColourBand(row._composite);
              const bandInfo = COLOUR_BANDS[band];
              const isSelected = row.ticker === selectedTicker;
              const prevComposite = prevMap.get(row.ticker);
              const delta = prevComposite != null ? row._composite - prevComposite : null;

              return (
                <tr
                  key={row.ticker}
                  onClick={() => onSelectRow(row)}
                  className={cn(
                    'border-b border-muted/30 cursor-pointer transition-colors',
                    isSelected ? 'bg-primary/10' : 'hover:bg-muted/30',
                    row.is_shortlisted && 'border-l-2 border-l-emerald-500',
                  )}
                >
                  <td className="px-3 py-2 text-muted-foreground tabular-nums">{row.rank}</td>
                  <td className="px-3 py-2">
                    <div className="font-medium">{row.ticker.replace('.NS', '').replace('.BO', '')}</div>
                    <div className="text-muted-foreground truncate max-w-36">{row.company_name}</div>
                  </td>
                  <td className="px-3 py-2 text-muted-foreground truncate max-w-28">{row.industry}</td>
                  <td className="px-3 py-2">
                    <div className="flex items-center gap-1">
                      <span className={cn('font-semibold tabular-nums', bandInfo.className.split(' ')[0])}>
                        {row._composite.toFixed(1)}
                      </span>
                      {delta != null && (
                        <span className={cn('text-xs tabular-nums', delta >= 0 ? 'text-emerald-400' : 'text-red-400')}>
                          {delta >= 0 ? '+' : ''}{delta.toFixed(1)}
                        </span>
                      )}
                    </div>
                    <ScreenerScoreBar score={row._composite} className="mt-0.5" />
                  </td>
                  {(['valuation_score', 'fundamentals_score', 'jhunjhunwala_score', 'growth_score', 'insider_score', 'technical_score'] as const).map((k) => (
                    <td key={k} className="px-3 py-2 tabular-nums text-muted-foreground">
                      {(row[k] as number)?.toFixed(0) ?? '—'}
                    </td>
                  ))}
                </tr>
              );
            })}
            {rows.length === 0 && (
              <tr>
                <td colSpan={10} className="px-3 py-8 text-center text-muted-foreground">
                  No results match your filter.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
