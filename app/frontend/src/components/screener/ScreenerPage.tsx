import { useState, useEffect, useRef, useCallback } from 'react';
import { screenerApi } from '@/services/screener-service';
import {
  ScreenerRunSummary,
  ScreenerResultRow,
  ThresholdMode,
  WeightProfileName,
  ProgressEvent,
  SSEEvent,
  BackfillSSEEvent,
  WeightValues,
} from './types';
import { PROFILES, computeCompositeClientSide } from './profiles';
import { apply_threshold_client } from './threshold';
import { ScreenerToolbar } from './ScreenerToolbar';
import { ScreenerShortlist } from './ScreenerShortlist';
import { ScreenerRankTable } from './ScreenerRankTable';
import { ScreenerRunProgress } from './ScreenerRunProgress';
import { ScreenerStockDetail } from './ScreenerStockDetail';
import { WeightSliders } from './WeightSliders';
import { CustomTickerSearch } from './CustomTickerSearch';

const DEFAULT_CUSTOM_WEIGHTS: WeightValues = {
  valuation: 20,
  fundamentals: 20,
  jhunjhunwala: 15,
  growth: 20,
  insider: 10,
  technical: 15,
};

// Load custom weights from localStorage
function loadCustomWeights(): WeightValues {
  try {
    const stored = localStorage.getItem('screener_custom_weights');
    if (stored) return JSON.parse(stored);
  } catch {}
  return DEFAULT_CUSTOM_WEIGHTS;
}

export function ScreenerPage() {
  const [runs, setRuns] = useState<ScreenerRunSummary[]>([]);
  const [activeRunId, setActiveRunId] = useState<number | null>(null);
  const [results, setResults] = useState<ScreenerResultRow[]>([]);
  const [prevResults, setPrevResults] = useState<ScreenerResultRow[]>([]);

  const [thresholdMode, setThresholdMode] = useState<ThresholdMode>('top25');
  const [weightProfile, setWeightProfile] = useState<WeightProfileName>('medium_long');
  const [customWeights, setCustomWeights] = useState<WeightValues>(loadCustomWeights());

  const [isRunning, setIsRunning] = useState(false);
  const [progressEvents, setProgressEvents] = useState<ProgressEvent[]>([]);
  const [progressDone, setProgressDone] = useState(0);
  const [progressTotal, setProgressTotal] = useState(0);

  const [isBackfilling, setIsBackfilling] = useState(false);
  const [backfillDay, setBackfillDay] = useState<{ day: number; totalDays: number; date: string } | undefined>(undefined);

  const [selectedRow, setSelectedRow] = useState<ScreenerResultRow | null>(null);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [showCustomSearch, setShowCustomSearch] = useState(false);

  const cancelRunRef = useRef<(() => void) | null>(null);
  const cancelBackfillRef = useRef<(() => void) | null>(null);

  // Load runs on mount
  useEffect(() => {
    screenerApi.listRuns(30)
      .then((r) => {
        setRuns(r);
        const completed = r.filter((x) => x.status === 'COMPLETE');
        if (completed.length > 0) {
          setActiveRunId(completed[0].id);
        }
      })
      .catch(console.error);
  }, []);

  // Load results when activeRunId changes (AC-0113)
  useEffect(() => {
    if (!activeRunId) return;
    screenerApi.getRunResults(activeRunId)
      .then(({ results: rows }) => {
        setResults(rows);
      })
      .catch(console.error);
  }, [activeRunId]);

  // Load previous run for delta badges (AC-0114)
  useEffect(() => {
    if (!activeRunId || runs.length < 2) return;
    const idx = runs.findIndex((r) => r.id === activeRunId);
    const prevRun = runs[idx + 1];
    if (!prevRun || prevRun.status !== 'COMPLETE') return;
    screenerApi.getRunResults(prevRun.id)
      .then(({ results: rows }) => setPrevResults(rows))
      .catch(() => {});
  }, [activeRunId, runs]);

  // Derive active profile weights
  const activeProfile = weightProfile !== 'custom' ? PROFILES[weightProfile] : null;
  const weights = activeProfile ? activeProfile.weights : customWeights;

  // Re-apply shortlisting client-side when threshold or weights change (AC-0109)
  const displayResults = apply_threshold_client(results, thresholdMode, weights);

  const handleRunScreener = useCallback(() => {
    if (isRunning) return;
    setIsRunning(true);
    setProgressEvents([]);
    setProgressDone(0);
    setProgressTotal(0);

    const cancel = screenerApi.triggerRun(
      {
        threshold_mode: thresholdMode,
        weight_profile: weightProfile,
        custom_weights: weightProfile === 'custom' ? customWeights : undefined,
      },
      (event: SSEEvent) => {
        if (event.type === 'progress') {
          setProgressEvents((prev) => [...prev, event]);
          setProgressDone(event.done);
          setProgressTotal(event.total);
        } else if (event.type === 'complete') {
          setIsRunning(false);
          // Reload run list and load the new run's results
          screenerApi.listRuns(30).then((r) => {
            setRuns(r);
            setActiveRunId(event.run_id);
          });
        } else if (event.type === 'error') {
          setIsRunning(false);
          console.error('Screener run error:', event.message);
        }
      },
      (err) => {
        setIsRunning(false);
        console.error('Screener connection error:', err);
      },
    );
    cancelRunRef.current = cancel;
  }, [isRunning, thresholdMode, weightProfile, customWeights]);

  const handleBackfill = useCallback(() => {
    if (isRunning || isBackfilling) return;
    setIsBackfilling(true);
    setProgressEvents([]);
    setProgressDone(0);
    setProgressTotal(0);
    setBackfillDay(undefined);

    const cancel = screenerApi.triggerBackfill(
      false,
      (event: BackfillSSEEvent) => {
        if (event.type === 'backfill_day_start') {
          setBackfillDay({ day: event.day, totalDays: event.total_days, date: event.date });
          setProgressEvents([]);
          setProgressDone(0);
          setProgressTotal(0);
        } else if (event.type === 'progress') {
          setProgressEvents((prev) => [...prev, event]);
          setProgressDone(event.done);
          setProgressTotal(event.total);
        } else if (event.type === 'backfill_day_complete') {
          // Refresh run list to pick up the newly completed day
          screenerApi.listRuns(30).then((r) => {
            setRuns(r);
            setActiveRunId(event.run_id);
          });
        } else if (event.type === 'backfill_complete') {
          setIsBackfilling(false);
          setBackfillDay(undefined);
          // Final refresh
          screenerApi.listRuns(30).then((r) => setRuns(r));
        } else if (event.type === 'error') {
          setIsBackfilling(false);
          setBackfillDay(undefined);
          console.error('Backfill error:', (event as { message?: string }).message);
        }
      },
      (err) => {
        setIsBackfilling(false);
        setBackfillDay(undefined);
        console.error('Backfill connection error:', err);
      },
    );
    cancelBackfillRef.current = cancel;
  }, [isRunning, isBackfilling]);

  const handleRefreshConstituents = async () => {
    setIsRefreshing(true);
    try {
      const r = await screenerApi.refreshConstituents();
      alert(`Constituent refresh complete.\nAdded: ${r.added.length}, Removed: ${r.removed.length}, Total: ${r.total}`);
    } catch (err) {
      console.error('Refresh failed:', err);
    } finally {
      setIsRefreshing(false);
    }
  };

  const handleCustomWeightsChange = (w: WeightValues) => {
    setCustomWeights(w);
    localStorage.setItem('screener_custom_weights', JSON.stringify(w));
  };

  const handleRunFullAnalysis = (ticker: string) => {
    // Open the hedge fund run with this ticker — user can configure from there
    window.dispatchEvent(new CustomEvent('screener:run-full-analysis', { detail: { ticker } }));
  };

  return (
    <div className="h-full flex flex-col bg-background overflow-hidden">
      <ScreenerToolbar
        runs={runs}
        activeRunId={activeRunId}
        isRunning={isRunning}
        isBackfilling={isBackfilling}
        thresholdMode={thresholdMode}
        weightProfile={weightProfile}
        onRunScreener={handleRunScreener}
        onBackfill={handleBackfill}
        onSelectRun={setActiveRunId}
        onThresholdChange={setThresholdMode}
        onWeightProfileChange={setWeightProfile}
        onRefreshConstituents={handleRefreshConstituents}
        isRefreshing={isRefreshing}
      />

      <div className="flex flex-1 overflow-hidden">
        {/* Main content */}
        <div className="flex-1 flex flex-col overflow-hidden">
          {/* Progress banner (single run or backfill) */}
          {(isRunning || isBackfilling) && (
            <div className="px-4 py-3 border-b shrink-0">
              <ScreenerRunProgress
                events={progressEvents}
                done={progressDone}
                total={progressTotal}
                isRunning={isRunning || isBackfilling}
                backfill={backfillDay}
              />
            </div>
          )}

          {/* Custom weights panel */}
          {weightProfile === 'custom' && (
            <div className="px-4 py-2 border-b shrink-0">
              <WeightSliders
                weights={customWeights}
                onChange={handleCustomWeightsChange}
                disabled={isRunning}
              />
            </div>
          )}

          {/* Shortlist cards */}
          {displayResults.some((r) => r.is_shortlisted) && (
            <div className="px-4 py-3 border-b shrink-0 bg-emerald-500/3">
              <ScreenerShortlist
                results={displayResults}
                activeProfile={activeProfile}
                customWeights={customWeights}
                onSelectStock={setSelectedRow}
              />
            </div>
          )}

          {/* Rank table */}
          <div className="flex-1 overflow-hidden">
            {displayResults.length > 0 ? (
              <ScreenerRankTable
                results={displayResults}
                weights={weights}
                prevResults={prevResults.length > 0 ? prevResults : undefined}
                onSelectRow={setSelectedRow}
                selectedTicker={selectedRow?.ticker}
              />
            ) : !isRunning ? (
              <div className="flex flex-col items-center justify-center h-full gap-4 text-muted-foreground">
                <div className="text-center">
                  <div className="text-base font-medium mb-1">No screener data</div>
                  <div className="text-sm">Click "Run Screener" to score all Nifty 500 stocks</div>
                </div>
              </div>
            ) : null}
          </div>

          {/* Custom ticker search */}
          <div className="px-4 py-3 border-t shrink-0">
            <div
              className="text-xs text-muted-foreground cursor-pointer hover:text-foreground mb-2 flex items-center gap-1"
              onClick={() => setShowCustomSearch((p) => !p)}
            >
              <span>{showCustomSearch ? '▾' : '▸'}</span>
              Custom Ticker (outside Nifty 500)
            </div>
            {showCustomSearch && (
              <CustomTickerSearch
                weightProfile={weightProfile}
                customWeights={customWeights}
                onRunFullAnalysis={handleRunFullAnalysis}
              />
            )}
          </div>
        </div>

        {/* Detail drawer */}
        {selectedRow && (
          <div className="w-72 shrink-0 border-l">
            <ScreenerStockDetail
              row={selectedRow}
              weights={weights}
              onClose={() => setSelectedRow(null)}
              onRunFullAnalysis={handleRunFullAnalysis}
            />
          </div>
        )}
      </div>
    </div>
  );
}
