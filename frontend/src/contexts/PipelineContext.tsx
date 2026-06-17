/**
 * PipelineContext — single polling source for pipeline status (Phase 13.5).
 *
 * Instead of each component independently polling /api/orchestrator/status,
 * this context polls once and shares the result via React context.
 */
import { createContext, useContext, useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { api } from '../hooks/api';
import { POLLING_INTERVAL_MS, POLLING_INTERVAL_IDLE_MS } from '../constants';
import type { PipelineStatus } from '../types';

interface PipelineContextValue {
  status: PipelineStatus | null;
  loading: boolean;
  error: string | null;
  refresh: () => void;
}

const PipelineContext = createContext<PipelineContextValue>({
  status: null,
  loading: true,
  error: null,
  refresh: () => {},
});

export function PipelineProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<PipelineStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const currentIntervalMs = useRef(POLLING_INTERVAL_MS);

  const fetchStatus = useCallback(async () => {
    try {
      const data = await api.getPipelineStatus();
      setStatus(data);
      setError(null);

      // Phase 14.4: adaptive polling — slower when idle, faster when running
      const isIdle = data.pipeline_status === 'IDLE' || data.pipeline_status === 'PIPELINE_COMPLETE';
      const targetInterval = isIdle ? POLLING_INTERVAL_IDLE_MS : POLLING_INTERVAL_MS;
      if (targetInterval !== currentIntervalMs.current) {
        currentIntervalMs.current = targetInterval;
        if (intervalRef.current) clearInterval(intervalRef.current);
        intervalRef.current = setInterval(fetchStatus, targetInterval);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to fetch status');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchStatus();
    intervalRef.current = setInterval(fetchStatus, POLLING_INTERVAL_MS);
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [fetchStatus]);

  return (
    <PipelineContext.Provider value={{ status, loading, error, refresh: fetchStatus }}>
      {children}
    </PipelineContext.Provider>
  );
}

export function usePipelineStatus() {
  return useContext(PipelineContext);
}
