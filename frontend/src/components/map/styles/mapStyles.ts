/**
 * MapLibre basemap styles on CARTO raster tiles. CARTO requires an API key
 * (unkeyed tiles are watermarked); MaplibreViewer passes one from
 * useBasemapConfig() via buildBasemapStyle(). The key is served by the
 * backend at GET /api/basemap-config.
 */

export type BasemapTheme = 'dark' | 'light';

const CARTO_SUBDOMAINS = ['a', 'b', 'c', 'd'] as const;
const CARTO_RASTER_STYLE: Record<BasemapTheme, string> = {
  dark: 'dark_all',
  light: 'light_all',
};
const GLYPHS_URL = 'https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf';

// Declared on the raster source so MapLibre's AttributionControl shows it
// even without the custom list in MaplibreViewer. Same markup as that list so
// the control de-duplicates instead of showing both.
export const OSM_ATTRIBUTION_HTML =
  '<a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">© OpenStreetMap contributors</a>';
export const CARTO_ATTRIBUTION_HTML =
  '<a href="https://carto.com/attribution" target="_blank" rel="noopener">CARTO</a>';

/** Tile URL templates for a CARTO raster style, keyed when a key is supplied. */
export function cartoTileUrls(theme: BasemapTheme, cartoApiKey?: string | null): string[] {
  const style = CARTO_RASTER_STYLE[theme];
  const key = (cartoApiKey || '').trim();
  const query = key ? `?key=${encodeURIComponent(key)}` : '';
  return CARTO_SUBDOMAINS.map(
    (s) => `https://${s}.basemaps.cartocdn.com/rastertiles/${style}/{z}/{x}/{y}@2x.png${query}`,
  );
}

export function buildBasemapStyle(theme: BasemapTheme, cartoApiKey?: string | null) {
  const sourceId = `carto-${theme}`;
  return {
    version: 8,
    glyphs: GLYPHS_URL,
    sources: {
      [sourceId]: {
        type: 'raster',
        tiles: cartoTileUrls(theme, cartoApiKey),
        tileSize: 256,
        attribution: `${OSM_ATTRIBUTION_HTML} ${CARTO_ATTRIBUTION_HTML}`,
      },
    },
    layers: [
      { id: `${sourceId}-layer`, type: 'raster', source: sourceId, minzoom: 0, maxzoom: 22 },
      { id: 'imagery-ceiling', type: 'background', paint: { 'background-opacity': 0 } },
    ],
  };
}

export const darkStyle = buildBasemapStyle('dark');
export const lightStyle = buildBasemapStyle('light');
