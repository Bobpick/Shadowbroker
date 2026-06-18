import { describe, it, expect } from 'vitest';
import { buildSarScenesGeoJSON } from '@/components/map/geoJSONBuilders';
import type { SarScene } from '@/types/dashboard';

describe('buildSarScenesGeoJSON', () => {
  it('builds footprint and center pin per scene', () => {
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
    const fc = buildSarScenesGeoJSON(scenes);
    expect(fc?.features).toHaveLength(2);
    expect(fc?.features.some((f) => f.properties?.type === 'sar_scene')).toBe(true);
    expect(fc?.features.some((f) => f.properties?.type === 'sar_scene_footprint')).toBe(true);
  });
});