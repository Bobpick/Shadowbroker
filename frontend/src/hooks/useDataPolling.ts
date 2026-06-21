import { useEffect, useRef } from "react";
import { API_BASE } from "@/lib/api";
import { mergeData, setBackendStatus as setStoreBackendStatus } from "./useDataStore";
import { appendLiveDataBoundsParams, liveDataBoundsKey } from "@/lib/liveDataViewport";
import { VIEWPORT_COMMITTED_EVENT } from "@/components/map/hooks/useViewportBounds";

export type BackendStatus = 'connecting' | 'connected' | 'disconnected';

// ---------------------------------------------------------------------------
// Polling pause/resume — used by Time Machine snapshot playback
// ---------------------------------------------------------------------------
let _pollingPaused = false;
let _fastEtagRef: { current: string | null } | null = null;
let _slowEtagRef: { current: string | null } | null = null;

/** Pause live data polling (snapshot mode). */
export function pausePolling() {
  _pollingPaused = true;
}

/** Resume live data polling and invalidate ETags for a full refresh. */
export function resumePolling() {
  _pollingPaused = false;
  // Invalidate ETags so the next poll gets fresh data (not 304)
  if (_fastEtagRef) _fastEtagRef.current = null;
  if (_slowEtagRef) _slowEtagRef.current = null;
}

/** Resume live mode and fetch both live tiers immediately instead of waiting for the next poll tick. */
export async function forceRefreshLiveData(): Promise<void> {
  _pollingPaused = false;
  if (_fastEtagRef) _fastEtagRef.current = null;
  if (_slowEtagRef) _slowEtagRef.current = null;

  try {
    const [fastRes, slowRes] = await Promise.all([
      fetch(appendLiveDataBoundsParams(`${API_BASE}/api/live-data/fast`)),
      fetch(appendLiveDataBoundsParams(`${API_BASE}/api/live-data/slow`)),
    ]);

    if (fastRes.ok) {
      if (_fastEtagRef) _fastEtagRef.current = fastRes.headers.get('etag') || null;
      mergeData(await fastRes.json());
    }
    if (slowRes.ok) {
      if (_slowEtagRef) _slowEtagRef.current = slowRes.headers.get('etag') || null;
      mergeData(await slowRes.json());
    }
    if (fastRes.ok || slowRes.ok) {
      setStoreBackendStatus('connected');
    }
  } catch (e) {
    console.error("Failed forcing live data refresh", e);
    setStoreBackendStatus('disconnected');
  }
}
type FastDataProbe = {
  commercial_flights?: unknown[];
  military_flights?: unknown[];
  tracked_flights?: unknown[];
  ships?: unknown[];
  sigint?: unknown[];
  cctv?: unknown[];
  news?: unknown[];
  threat_level?: unknown;
};

function hasMeaningfulFastData(json: FastDataProbe): boolean {
  return (
    (json.commercial_flights?.length || 0) > 100 ||
    (json.military_flights?.length || 0) > 25 ||
    (json.tracked_flights?.length || 0) > 10 ||
    (json.ships?.length || 0) > 100 ||
    (json.sigint?.length || 0) > 100 ||
    (json.cctv?.length || 0) > 100
  );
}

/**
 * Event name dispatched by page.tsx when a layer toggle changes.
 * useDataPolling listens for this to immediately refetch slow-tier data
 * so toggled layers (power plants, GDELT, etc.) appear without the usual
 * 120-second wait.
 */
export const LAYER_TOGGLE_EVENT = 'sb:layer-toggle';

/** Debounce rapid pans; min gap keeps viewport refetches under the 120/min rate limit. */
const VIEWPORT_FAST_REFETCH_DEBOUNCE_MS = 400;
const VIEWPORT_FAST_REFETCH_MIN_INTERVAL_MS = 2500;

/** Steady-state poll cadence (must match scheduleNext delays). */
const FAST_POLL_MS = 15_000;
const SLOW_POLL_MS = 120_000;

/** Abort hung proxy/backend fetches so the poll chain cannot stall indefinitely. */
const FAST_FETCH_TIMEOUT_MS = 45_000;
const SLOW_FETCH_TIMEOUT_MS = 90_000;

/** Watchdog checks whether polls are still advancing (background tab timer throttling). */
const KEEPALIVE_WATCHDOG_MS = 30_000;
const FAST_STALE_MS = FAST_POLL_MS * 4;
const SLOW_STALE_MS = SLOW_POLL_MS * 2;

/** Lightweight backend ping so long-lived tabs keep the proxy connection warm. */
const HEALTH_PING_MS = 4 * 60_000;

/**
 * Polls the backend for fast and slow data tiers.
 *
 * Issue #288: heavy, density-driven layers (vessels, aircraft, gdelt
 * events, fires, sigint, …) are bbox-scoped to the visible map area via
 * `appendLiveDataBoundsParams`. Static reference layers (datacenters,
 * military bases, power plants, satellites, weather, news, …) are NOT
 * filtered backend-side, so panning never reveals an "empty world" of
 * infrastructure. World-zoomed views skip bbox params entirely and hit
 * the shared ETag cache exactly like the pre-#288 behaviour.
 *
 * Viewport commits trigger a debounced fast-tier refetch so regional pans
 * refill aircraft/ships without waiting for the 15s poll cadence.
 *
 * The AIS stream viewport POST (/api/viewport) is still handled separately
 * by useViewportBounds to limit upstream AIS ingestion.
 */
export function useDataPolling() {
  const fastEtag = useRef<string | null>(null);
  const slowEtag = useRef<string | null>(null);

  useEffect(() => {
    // Expose refs so pausePolling/resumePolling can invalidate ETags
    _fastEtagRef = fastEtag;
    _slowEtagRef = slowEtag;

    let hasData = false;
    let fetchedStartupFastPayload = false;
    let fastTimerId: ReturnType<typeof setTimeout> | null = null;
    let slowTimerId: ReturnType<typeof setTimeout> | null = null;
    let viewportDebounceTimer: ReturnType<typeof setTimeout> | null = null;
    const fastAbortRef = { current: null as AbortController | null };
    const slowAbortRef = { current: null as AbortController | null };
    const fastFetchGenRef = { current: 0 };
    let lastViewportFetchKey: string | null = null;
    let lastViewportFetchAt = 0;
    let lastFastPollAt = Date.now();
    let lastSlowPollAt = Date.now();

    const touchFastPoll = () => {
      lastFastPollAt = Date.now();
    };

    const touchSlowPoll = () => {
      lastSlowPollAt = Date.now();
    };

    const armFetchTimeout = (controller: AbortController, timeoutMs: number) => {
      return window.setTimeout(() => controller.abort(), timeoutMs);
    };

    const wakeLiveData = () => {
      if (_pollingPaused) return;
      fastEtag.current = null;
      slowEtag.current = null;
      void forceRefreshLiveData();
    };

    const fetchCriticalBootstrap = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/bootstrap/critical`, {
          headers: { Accept: 'application/json' },
        });
        if (res.ok) {
          setStoreBackendStatus('connected');
          const json = await res.json();
          mergeData(json);
          if (hasMeaningfulFastData(json) || (json.news?.length || 0) > 0 || json.threat_level) {
            hasData = true;
          }
        }
      } catch (e) {
        const aborted =
          typeof e === 'object' &&
          e !== null &&
          'name' in e &&
          (e as { name?: string }).name === 'AbortError';
        if (!aborted) {
          console.warn("Critical bootstrap fetch will retry via live polling", e);
        }
      }
    };

    const abortInFlightFastFetch = () => {
      if (fastAbortRef.current) {
        fastAbortRef.current.abort();
        fastAbortRef.current = null;
      }
    };

    const fetchFastData = async () => {
      if (fastTimerId) {
        clearTimeout(fastTimerId);
        fastTimerId = null;
      }
      // Skip fetch when Time Machine snapshot mode is active
      if (_pollingPaused) { scheduleNext('fast'); return; }

      abortInFlightFastFetch();
      const controller = new AbortController();
      fastAbortRef.current = controller;
      const fetchGen = ++fastFetchGenRef.current;
      const timeoutId = armFetchTimeout(controller, FAST_FETCH_TIMEOUT_MS);

      try {
        const useStartupPayload = !fetchedStartupFastPayload && !fastEtag.current;
        const headers: Record<string, string> = {};
        if (!useStartupPayload && fastEtag.current) headers['If-None-Match'] = fastEtag.current;
        const url = appendLiveDataBoundsParams(
          `${API_BASE}/api/live-data/fast${useStartupPayload ? '?initial=1' : ''}`,
        );
        const res = await fetch(url, {
          headers,
          signal: controller.signal,
        });
        if (fetchGen !== fastFetchGenRef.current) return;
        touchFastPoll();
        if (res.status === 304) {
          setStoreBackendStatus('connected');
          return;
        }
        if (res.ok) {
          setStoreBackendStatus('connected');
          // Do not keep the capped startup ETag. The next steady poll should
          // request the full fast dataset and replace the representative first paint.
          fastEtag.current = useStartupPayload ? null : res.headers.get('etag') || null;
          if (useStartupPayload) fetchedStartupFastPayload = true;
          const json = await res.json();
          if (fetchGen !== fastFetchGenRef.current) return;
          mergeData(json);
          if (hasMeaningfulFastData(json)) hasData = true;
        }
      } catch (e) {
        const aborted =
          typeof e === 'object' &&
          e !== null &&
          'name' in e &&
          (e as { name?: string }).name === 'AbortError';
        if (!aborted) {
          console.warn("Fast live data fetch will retry after runtime is reachable", e);
          setStoreBackendStatus('disconnected');
        }
      } finally {
        window.clearTimeout(timeoutId);
        if (fastAbortRef.current === controller) {
          fastAbortRef.current = null;
        }
        if (fetchGen === fastFetchGenRef.current) {
          scheduleNext('fast', fetchGen);
        }
      }
    };

    const abortInFlightSlowFetch = () => {
      if (slowAbortRef.current) {
        slowAbortRef.current.abort();
        slowAbortRef.current = null;
      }
    };

    const fetchSlowData = async () => {
      if (slowTimerId) {
        clearTimeout(slowTimerId);
        slowTimerId = null;
      }
      if (_pollingPaused) {
        scheduleNext('slow');
        return;
      }

      abortInFlightSlowFetch();
      const controller = new AbortController();
      slowAbortRef.current = controller;
      const timeoutId = armFetchTimeout(controller, SLOW_FETCH_TIMEOUT_MS);

      try {
        const headers: Record<string, string> = {};
        if (slowEtag.current) headers['If-None-Match'] = slowEtag.current;
        const res = await fetch(
          appendLiveDataBoundsParams(`${API_BASE}/api/live-data/slow`),
          {
            headers,
            signal: controller.signal,
          },
        );
        touchSlowPoll();
        if (res.status === 304) return;
        if (res.ok) {
          slowEtag.current = res.headers.get('etag') || null;
          const json = await res.json();
          mergeData(json);
        }
      } catch (e) {
        const aborted =
          typeof e === 'object' &&
          e !== null &&
          'name' in e &&
          (e as { name?: string }).name === 'AbortError';
        if (!aborted) {
          console.warn("Slow live data fetch will retry after runtime is reachable", e);
        }
      } finally {
        window.clearTimeout(timeoutId);
        if (slowAbortRef.current === controller) {
          slowAbortRef.current = null;
        }
        scheduleNext('slow');
      }
    };

    // Adaptive polling: retry every 3s during startup, back off to normal cadence once data arrives
    const scheduleNext = (tier: 'fast' | 'slow', fetchGen?: number) => {
      if (tier === 'fast') {
        if (fetchGen !== undefined && fetchGen !== fastFetchGenRef.current) return;
        const delay = hasData ? FAST_POLL_MS : 3000; // 3s startup retry → steady state
        const needsFullFastPayload = fetchedStartupFastPayload && !fastEtag.current;
        fastTimerId = setTimeout(fetchFastData, needsFullFastPayload ? 750 : delay);
      } else {
        const delay = hasData ? SLOW_POLL_MS : 5000; // 5s startup retry → steady state
        slowTimerId = setTimeout(fetchSlowData, delay);
      }
    };

    const queueViewportFastRefetch = () => {
      if (_pollingPaused) return;

      const key = liveDataBoundsKey();
      if (!key) {
        lastViewportFetchKey = null;
        return;
      }
      if (key === lastViewportFetchKey) return;

      if (viewportDebounceTimer) clearTimeout(viewportDebounceTimer);
      viewportDebounceTimer = setTimeout(() => {
        viewportDebounceTimer = null;
        if (_pollingPaused) return;

        const currentKey = liveDataBoundsKey();
        if (!currentKey || currentKey === lastViewportFetchKey) return;

        const now = Date.now();
        if (now - lastViewportFetchAt < VIEWPORT_FAST_REFETCH_MIN_INTERVAL_MS) return;

        lastViewportFetchKey = currentKey;
        lastViewportFetchAt = now;
        fastEtag.current = null;
        void fetchFastData();
      }, VIEWPORT_FAST_REFETCH_DEBOUNCE_MS);
    };

    // When a layer toggle fires, immediately refetch slow data so the user
    // doesn't wait up to 120s for power plants / GDELT / etc. to appear.
    const onLayerToggle = () => {
      slowEtag.current = null;           // invalidate ETag → guarantees fresh payload
      if (slowTimerId) clearTimeout(slowTimerId);
      slowTimerId = null;
      fetchSlowData();
    };
    const onVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        wakeLiveData();
      }
    };

    const onWindowFocus = () => {
      wakeLiveData();
    };

    const onPageShow = (event: PageTransitionEvent) => {
      if (event.persisted) {
        wakeLiveData();
      }
    };

    const onOnline = () => {
      wakeLiveData();
    };

    const watchdogId = window.setInterval(() => {
      if (_pollingPaused) return;
      const now = Date.now();
      const fastStale = now - lastFastPollAt > FAST_STALE_MS;
      const slowStale = now - lastSlowPollAt > SLOW_STALE_MS;
      if (fastStale) {
        console.info('Keepalive: restarting stale fast live-data polling');
        fastEtag.current = null;
        void fetchFastData();
      }
      if (slowStale) {
        console.info('Keepalive: restarting stale slow live-data polling');
        slowEtag.current = null;
        void fetchSlowData();
      }
    }, KEEPALIVE_WATCHDOG_MS);

    const healthPingId = window.setInterval(() => {
      if (_pollingPaused || document.visibilityState === 'hidden') return;
      void fetch(`${API_BASE}/api/health`, { cache: 'no-store' }).catch(() => {
        /* watchdog + tier polls own reconnection */
      });
    }, HEALTH_PING_MS);

    window.addEventListener(LAYER_TOGGLE_EVENT, onLayerToggle);
    window.addEventListener(VIEWPORT_COMMITTED_EVENT, queueViewportFastRefetch);
    document.addEventListener('visibilitychange', onVisibilityChange);
    window.addEventListener('focus', onWindowFocus);
    window.addEventListener('pageshow', onPageShow);
    window.addEventListener('online', onOnline);

    void (async () => {
      await fetchCriticalBootstrap();
      fetchFastData();
      // Let the bootstrap/fast payload paint before competing with the slow tier.
      slowTimerId = setTimeout(fetchSlowData, 5000);
    })();

    return () => {
      window.removeEventListener(LAYER_TOGGLE_EVENT, onLayerToggle);
      window.removeEventListener(VIEWPORT_COMMITTED_EVENT, queueViewportFastRefetch);
      document.removeEventListener('visibilitychange', onVisibilityChange);
      window.removeEventListener('focus', onWindowFocus);
      window.removeEventListener('pageshow', onPageShow);
      window.removeEventListener('online', onOnline);
      window.clearInterval(watchdogId);
      window.clearInterval(healthPingId);
      if (fastTimerId) clearTimeout(fastTimerId);
      if (slowTimerId) clearTimeout(slowTimerId);
      if (viewportDebounceTimer) clearTimeout(viewportDebounceTimer);
      abortInFlightFastFetch();
      abortInFlightSlowFetch();
    };
  }, []);

  // Data and backend status are now accessed via useDataStore hooks
  // (useDataKey, useDataKeys, useDataSnapshot, useBackendStatus).
  // This hook is a pure side-effect — it starts polling and writes to the store.
}
