import { describe, it, expect } from 'vitest';
import { buildSarAnomaliesGeoJSON } from '@/components/map/geoJSONBuilders';
import type { SarAoi, SarAnomaly } from '@/types/dashboard';

describe('buildSarAnomaliesGeoJSON', () => {
  const aoi: SarAoi = {
    id: 'test_aoi',
    name: 'Test',
    center: [38.5, -121.5],
    radius_km: 40,
    category: 'watchlist',
  };

  it('defaults to excavation kinds and pins inside AOI', () => {
    const anomalies: SarAnomaly[] = [
      {
        anomaly_id: 'water-far',
        kind: 'surface_water_change',
        lat: 45,
        lon: -115,
        magnitude: 0,
        magnitude_unit: '',
        confidence: 0.8,
        first_seen: 1,
        last_seen: 2,
        aoi_id: 'test_aoi',
        scene_count: 1,
        solver: 'OPERA-DSWx-S1',
        source_constellation: 'Sentinel-1',
        provenance_url: '',
        category: 'watchlist',
        title: 'water',
        summary: 'water',
      },
      {
        anomaly_id: 'veg-near',
        kind: 'vegetation_disturbance',
        lat: 50,
        lon: -130,
        magnitude: 0,
        magnitude_unit: '',
        confidence: 0.8,
        first_seen: 3,
        last_seen: 4,
        aoi_id: 'test_aoi',
        scene_count: 1,
        solver: 'OPERA-DIST-ALERT',
        source_constellation: 'HLS',
        provenance_url: '',
        category: 'watchlist',
        title: 'clearing',
        summary: 'clearing',
      },
    ];

    const fc = buildSarAnomaliesGeoJSON(anomalies, [aoi], 'excavation');
    expect(fc?.features).toHaveLength(1);
    expect(fc?.features[0]?.properties?.kind).toBe('vegetation_disturbance');
    const [lon, lat] = (fc?.features[0]?.geometry as GeoJSON.Point).coordinates;
    expect(Math.abs(lat - aoi.center[0])).toBeLessThan(0.5);
    expect(Math.abs(lon - aoi.center[1])).toBeLessThan(0.5);
  });
});