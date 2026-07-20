import { SSEEvent, BackfillSSEEvent, ScreenerRunSummary, ScreenerResultRow, WeightProfileName, WeightValues, ThresholdMode } from '@/components/screener/types';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

export const screenerApi = {
  listRuns: async (limit = 30): Promise<ScreenerRunSummary[]> => {
    const res = await fetch(`${API_BASE_URL}/screener/runs?limit=${limit}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
  },

  getRunResults: async (runId: number): Promise<{ run: ScreenerRunSummary; results: ScreenerResultRow[] }> => {
    const res = await fetch(`${API_BASE_URL}/screener/runs/${runId}/results`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
  },

  getTickerResult: async (runId: number, ticker: string): Promise<ScreenerResultRow> => {
    const res = await fetch(`${API_BASE_URL}/screener/runs/${runId}/results/${ticker}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
  },

  scoreCustomTicker: async (
    ticker: string,
    weightProfile: WeightProfileName = 'medium_long',
    customWeights?: WeightValues,
  ): Promise<ScreenerResultRow> => {
    const res = await fetch(`${API_BASE_URL}/screener/ticker`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ticker, weight_profile: weightProfile, custom_weights: customWeights }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
  },

  getConstituents: async () => {
    const res = await fetch(`${API_BASE_URL}/screener/constituents`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
  },

  refreshConstituents: async () => {
    const res = await fetch(`${API_BASE_URL}/screener/constituents/refresh`, { method: 'POST' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
  },

  /**
   * Trigger a screener run and stream SSE events.
   * Calls onEvent for each SSE event until complete or error.
   * Returns a cancel function.
   */
  triggerRun: (
    params: {
      threshold_mode: ThresholdMode;
      weight_profile: WeightProfileName;
      custom_weights?: WeightValues;
      run_date?: string;
    },
    onEvent: (event: SSEEvent) => void,
    onError: (err: Error) => void,
  ): (() => void) => {
    const controller = new AbortController();

    (async () => {
      try {
        const res = await fetch(`${API_BASE_URL}/screener/run`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(params),
          signal: controller.signal,
        });

        if (!res.ok || !res.body) {
          throw new Error(`HTTP ${res.status}`);
        }

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n');
          buffer = lines.pop() ?? '';

          for (const line of lines) {
            if (line.startsWith('data: ')) {
              try {
                const event = JSON.parse(line.slice(6)) as SSEEvent;
                onEvent(event);
              } catch {
                // malformed line — skip
              }
            }
          }
        }
      } catch (err) {
        if ((err as Error).name !== 'AbortError') {
          onError(err as Error);
        }
      }
    })();

    return () => controller.abort();
  },

  /**
   * Trigger 7-day backfill and stream SSE events.
   * Returns a cancel function.
   */
  triggerBackfill: (
    force: boolean = false,
    onEvent: (event: BackfillSSEEvent) => void,
    onError: (err: Error) => void,
  ): (() => void) => {
    const controller = new AbortController();

    (async () => {
      try {
        const res = await fetch(`${API_BASE_URL}/screener/backfill`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ force }),
          signal: controller.signal,
        });

        if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n');
          buffer = lines.pop() ?? '';
          for (const line of lines) {
            if (line.startsWith('data: ')) {
              try {
                onEvent(JSON.parse(line.slice(6)) as BackfillSSEEvent);
              } catch { /* malformed */ }
            }
          }
        }
      } catch (err) {
        if ((err as Error).name !== 'AbortError') onError(err as Error);
      }
    })();

    return () => controller.abort();
  },
};
