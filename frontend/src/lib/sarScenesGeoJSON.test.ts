import { describe, it, expect } from 'vitest';
import { buildSarScenesGeoJSON } from '@/components/map/geoJSONBuilders';
import type { SarAoi, SarScene } from '@/types/dashboard';

describe('buildSarScenesGeoJSON', () => {
  const oregonAoi: SarAoi = {
    id: 'oregon',
    name: 'Oregon',
    center: [44, -120.5],
    radius_km: 80,
    category: 'watchlist',
  };

  it('anchors scene pins inside the matching AOI circle', () => {
    const scenes: SarScene[] = [
      {
        scene_id: 'S1A_2026_06_12',
        platform: 'Sentinel-1A',
        mode: 'IW',
        level: 'GRD',
        time: '2026-06-12T18:22:00Z',
        aoi_id: 'oregon',
        relative_orbit: 42,
        flight_direction: 'ASCENDING',
        bbox: [-125, 42, -120, 46],
        download_url: 'https://example.com/scene',
        provider: 'ASF',
      },
    ];
    const fc = buildSarScenesGeoJSON(scenes, [oregonAoi]);
    expect(fc?.features).toHaveLength(1);
    const pin = fc?.features[0];
    expect(pin?.properties?.type).toBe('sar_scene');
    const [lon, lat] = (pin?.geometry as GeoJSON.Point).coordinates;
    const dLat = Math.abs(lat - oregonAoi.center[0]);
    const dLon = Math.abs(lon - oregonAoi.center[1]);
    expect(dLat).toBeLessThan(0.5);
    expect(dLon).toBeLessThan(0.5);
  });

  it('skips scenes without a matching AOI', () => {
    const scenes: SarScene[] = [
      {
        scene_id: 'orphan',
        platform: 'Sentinel-1A',
        mode: 'IW',
        level: 'GRD',
        time: '2026-06-12T18:22:00Z',
        aoi_id: 'nowhere',
        relative_orbit: 1,
        flight_direction: 'ASCENDING',
        bbox: [-125, 42, -120, 46],
        download_url: '',
        provider: 'ASF',
      },
    ];
    expect(buildSarScenesGeoJSON(scenes, [oregonAoi])).toBeNull();
  });
});