/**
 * Shared module-level state for the current map viewport bounds, used by
 * `useDataPolling` to scope `/api/live-data/{fast,slow}` to the visible
 * area when the user has zoomed in.
 *
 * Issue #288: the backend now bbox-filters dense layers (vessels, aircraft,
 * gdelt events, fires, sigint, …) when all four bounds are supplied. Light
 * reference layers stay world-scale. Heavy collections aren't sent over the
 * wire for parts of the planet the operator isn't looking at, which cuts
 * the steady-state poll from ~27 MB to ~5 MB for a typical regional view.
 *
 * No bounds set → callers omit the params entirely → backend ships full
 * world data (byte-identical to pre-#288 behaviour). This keeps the cold
 * boot path (where no map is mounted yet) and the world-zoomed view
 * unchanged.
 */

export interface LiveDataBounds {
  south: number;
  west: number;
  north: number;
  east: number;
}

let _current: LiveDataBounds | null = null;

/** True when lng_span ≥ 300 OR lat_span ≥ 120. Backend treats these as
 *  world-scale and skips filtering — so the frontend doesn't bother sending
 *  bounds at all, which keeps the ETag cache shared across operators in the
 *  zoomed-out case. */
function isEffectivelyWorld(bounds: LiveDataBounds): boolean {
  const latSpan = Math.max(0, bounds.north - bounds.south);
  let lngSpan = bounds.east - bounds.west;
  if (lngSpan < 0) lngSpan += 360;
  return lngSpan >= 300 || latSpan >= 120;
}

/** Push the latest committed bounds. Called from `useViewportBounds`
 *  whenever the map's bounds change enough to matter. Pass `null` to
 *  fall back to world-scale fetching (e.g. on unmount). */
export function setLiveDataBounds(bounds: LiveDataBounds | null): void {
  if (bounds === null) {
    _current = null;
    return;
  }
  if (
    !Number.isFinite(bounds.south) ||
    !Number.isFinite(bounds.west) ||
    !Number.isFinite(bounds.north) ||
    !Number.isFinite(bounds.east)
  ) {
    _current = null;
    return;
  }
  if (isEffectivelyWorld(bounds)) {
    // World-zoomed → fetch globally, share the ETag cache across operators.
    _current = null;
    return;
  }
  _current = bounds;
}

/** Read the current bounds, or `null` if the caller should fetch the full
 *  world payload. Reader contract: must tolerate `null` and call without
 *  bbox params in that case. */
export function getLiveDataBounds(): LiveDataBounds | null {
  return _current;
}

/** Stable cache key for the active bbox-scoped fetch window (1° quantization,
 *  matching appendLiveDataBoundsParams / backend ETag). Returns null when
 *  world-scale fetching is active. */
function quantizeBounds(b: LiveDataBounds): LiveDataBounds {
  const qFloor = (n: number) => Math.floor(n * 100) / 100;
  const qCeil = (n: number) => Math.ceil(n * 100) / 100;
  return {
    south: qFloor(b.south),
    west: qFloor(b.west),
    north: qCeil(b.north),
    east: qCeil(b.east),
  };
}

export function liveDataBoundsKey(): string | null {
  const b = _current;
  if (!b) return null;
  const q = quantizeBounds(b);
  return `${q.south.toFixed(2)},${q.west.toFixed(2)},${q.north.toFixed(2)},${q.east.toFixed(2)}`;
}

/** Append `s/w/n/e` query params to a URL when bounds are set, otherwise
 *  return the URL unchanged. Centralised so all live-data callers stay in
 *  sync about quantization and the world-scale skip rule. */
export function appendLiveDataBoundsParams(url: string): string {
  const b = _current;
  if (!b) return url;
  const sep = url.includes('?') ? '&' : '?';
  const q = quantizeBounds(b);
  return `${url}${sep}s=${q.south.toFixed(2)}&w=${q.west.toFixed(2)}&n=${q.north.toFixed(2)}&e=${q.east.toFixed(2)}`;
}
