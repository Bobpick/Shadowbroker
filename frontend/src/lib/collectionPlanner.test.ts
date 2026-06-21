import { buildCollectionPlanner, buildCollectionPlannerFromGtContext } from '@/lib/collectionPlanner';
import type { PointWeather } from '@/types/dashboard';

describe('buildCollectionPlanner', () => {
  it('recommends SAR when optical window is poor', () => {
    const weather: PointWeather = {
      optical_window: { status: 'poor', summary: 'Heavy cloud' },
      hourly_next_48h: [
        { time: '2026-06-18T12:00', cloud_cover_pct: 95 },
        { time: '2026-06-18T13:00', cloud_cover_pct: 90 },
      ],
    };
    const badge = buildCollectionPlanner(weather);
    expect(badge?.sarRecommended).toBe(true);
    expect(badge?.headline).toBe('SAR RECOMMENDED');
  });

  it('returns null when weather has an error', () => {
    expect(buildCollectionPlanner({ error: 'unavailable' })).toBeNull();
  });

  it('builds SAR badge from GT weather context', () => {
    const badge = buildCollectionPlannerFromGtContext({
      optical_status: 'poor',
      collection_recommendation: 'sar_recommended',
      collection_badge: 'OPTICAL: POOR — SAR RECOMMENDED',
    });
    expect(badge?.sarRecommended).toBe(true);
  });
});