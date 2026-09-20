import fs from 'fs';
import path from 'path';
import { act, cleanup, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  CARTO_ATTRIBUTION_HTML,
  OSM_ATTRIBUTION_HTML,
  buildBasemapStyle,
  cartoTileUrls,
  darkStyle,
  lightStyle,
} from '@/components/map/styles/mapStyles';
import {
  BASEMAP_CONFIG_HARD_TIMEOUT_MS,
  BASEMAP_CONFIG_SOFT_TIMEOUT_MS,
  __resetBasemapConfigCache,
  useBasemapConfig,
} from '@/hooks/useBasemapConfig';

const VIEWER_SRC = fs.readFileSync(
  path.join(__dirname, '..', '..', 'components', 'MaplibreViewer.tsx'),
  'utf-8',
);

describe('buildBasemapStyle', () => {
  it('produces unkeyed CARTO tile URLs when no key is given', () => {
    const style = buildBasemapStyle('dark');
    const source = style.sources['carto-dark'];
    expect(source.tiles).toHaveLength(4);
    for (const url of source.tiles) {
      expect(url).toMatch(/^https:\/\/[abcd]\.basemaps\.cartocdn\.com\/rastertiles\/dark_all\//);
      expect(url).not.toContain('?');
    }
    expect(style.layers[0]).toMatchObject({ id: 'carto-dark-layer', source: 'carto-dark' });
  });

  it('appends ?key= to every tile URL when a key is given', () => {
    const style = buildBasemapStyle('light', 'my key');
    for (const url of style.sources['carto-light'].tiles) {
      expect(url).toMatch(/\/rastertiles\/light_all\/\{z\}\/\{x\}\/\{y\}@2x\.png\?key=my%20key$/);
    }
  });

  it('treats blank keys as unconfigured', () => {
    expect(cartoTileUrls('dark', '   ')).toEqual(cartoTileUrls('dark'));
    expect(cartoTileUrls('dark', null)).toEqual(cartoTileUrls('dark'));
  });

  it('keeps the key-less default exports in sync with the builder', () => {
    expect(darkStyle).toEqual(buildBasemapStyle('dark'));
    expect(lightStyle).toEqual(buildBasemapStyle('light'));
  });

  it('declares OpenStreetMap and CARTO attribution on the raster source, keyed or not', () => {
    for (const style of [buildBasemapStyle('dark'), buildBasemapStyle('light', 'k')]) {
      const source = Object.values(style.sources)[0];
      expect(source.attribution).toContain('openstreetmap.org/copyright');
      expect(source.attribution).toContain('carto.com/attribution');
    }
  });
});

describe('MaplibreViewer attribution and basemap gating', () => {
  it('still renders the explicit AttributionControl with the same OSM/CARTO markup', () => {
    // attributionControl={false} only disables the default control; the
    // explicit child below it is the visible attribution and must survive.
    expect(VIEWER_SRC).toContain('<AttributionControl');
    expect(VIEWER_SRC).toContain(OSM_ATTRIBUTION_HTML);
    expect(VIEWER_SRC).toContain(CARTO_ATTRIBUTION_HTML);
  });

  it('gates the map on the bounded basemap config, not on an open-ended request', () => {
    expect(VIEWER_SRC).toContain('{basemapConfigLoaded && (');
    expect(VIEWER_SRC).toMatch(/const \{ cartoApiKey, loaded: basemapConfigLoaded \} = useBasemapConfig\(\)/);
    expect(BASEMAP_CONFIG_SOFT_TIMEOUT_MS).toBeLessThan(BASEMAP_CONFIG_HARD_TIMEOUT_MS);
  });
});

describe('useBasemapConfig', () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    vi.useFakeTimers();
    __resetBasemapConfigCache();
    fetchMock.mockReset();
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  function jsonResponse(body: unknown, ok = true) {
    return Promise.resolve({ ok, json: () => Promise.resolve(body) } as Response);
  }

  it('starts pending and resolves with the key', async () => {
    fetchMock.mockReturnValue(jsonResponse({ carto: { configured: true, key: ' abc ' } }));
    const { result } = renderHook(() => useBasemapConfig());
    expect(result.current).toEqual({ cartoApiKey: null, loaded: false });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(result.current).toEqual({ cartoApiKey: 'abc', loaded: true });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(String(fetchMock.mock.calls[0][0])).toMatch(/\/api\/basemap-config$/);
  });

  it('fails open with the unkeyed config on a non-OK response', async () => {
    fetchMock.mockReturnValue(jsonResponse({ detail: 'nope' }, false));
    const { result } = renderHook(() => useBasemapConfig());
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(result.current).toEqual({ cartoApiKey: null, loaded: true });
  });

  it('fails open on a network error', async () => {
    fetchMock.mockRejectedValue(new TypeError('Failed to fetch'));
    const { result } = renderHook(() => useBasemapConfig());
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(result.current).toEqual({ cartoApiKey: null, loaded: true });
  });

  it('releases the map after the soft timeout, then applies a late key', async () => {
    let resolveFetch: (value: Response) => void = () => {};
    fetchMock.mockReturnValue(new Promise<Response>((resolve) => (resolveFetch = resolve)));
    const { result } = renderHook(() => useBasemapConfig());

    await act(async () => {
      await vi.advanceTimersByTimeAsync(BASEMAP_CONFIG_SOFT_TIMEOUT_MS);
    });
    expect(result.current).toEqual({ cartoApiKey: null, loaded: true });

    await act(async () => {
      resolveFetch({ ok: true, json: () => Promise.resolve({ carto: { key: 'late' } }) } as Response);
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(result.current).toEqual({ cartoApiKey: 'late', loaded: true });
  });

  it('aborts the request at the hard timeout and stays unkeyed', async () => {
    fetchMock.mockImplementation(
      (_url: string, init?: RequestInit) =>
        new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')));
        }),
    );
    const { result } = renderHook(() => useBasemapConfig());
    await act(async () => {
      await vi.advanceTimersByTimeAsync(BASEMAP_CONFIG_HARD_TIMEOUT_MS + 1);
    });
    expect(result.current).toEqual({ cartoApiKey: null, loaded: true });
    expect(fetchMock.mock.calls[0][1]?.signal?.aborted).toBe(true);
  });

  it('shares one request across mounts and caches only successes', async () => {
    fetchMock.mockReturnValue(jsonResponse({ carto: { key: 'shared' } }));
    const a = renderHook(() => useBasemapConfig());
    const b = renderHook(() => useBasemapConfig());
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(a.result.current.cartoApiKey).toBe('shared');
    expect(b.result.current.cartoApiKey).toBe('shared');
    expect(fetchMock).toHaveBeenCalledTimes(1);

    cleanup();
    const c = renderHook(() => useBasemapConfig());
    expect(c.result.current).toEqual({ cartoApiKey: 'shared', loaded: true });
    expect(fetchMock).toHaveBeenCalledTimes(1);

    __resetBasemapConfigCache();
    fetchMock.mockReturnValueOnce(jsonResponse({}, false));
    fetchMock.mockReturnValueOnce(jsonResponse({ carto: { key: 'second-try' } }));
    cleanup();
    const d = renderHook(() => useBasemapConfig());
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(d.result.current).toEqual({ cartoApiKey: null, loaded: true });
    cleanup();
    const e = renderHook(() => useBasemapConfig());
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(e.result.current).toEqual({ cartoApiKey: 'second-try', loaded: true });
  });
});
