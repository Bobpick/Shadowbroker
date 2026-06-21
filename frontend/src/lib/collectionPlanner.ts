import { opticalWindowColor } from '@/lib/weatherCodes';
import type { GtWeatherContext, PointWeather, PointWeatherOpticalWindow } from '@/types/dashboard';

export interface CollectionPlannerBadge {
  status: PointWeatherOpticalWindow['status'];
  headline: string;
  detail: string;
  color: string;
  sarRecommended: boolean;
}

function poorOpticalHours(hourly: PointWeather['hourly_next_48h']): number {
  if (!hourly?.length) return 0;
  let streak = 0;
  for (const row of hourly.slice(0, 48)) {
    const cloud = row.cloud_cover_pct;
    if (cloud == null || cloud >= 70) streak += 1;
    else break;
  }
  return streak;
}

export function buildCollectionPlannerFromGtContext(
  context?: GtWeatherContext | null,
): CollectionPlannerBadge | null {
  if (!context) return null;
  const status = (context.optical_status as PointWeatherOpticalWindow['status']) ?? 'unknown';
  const color = opticalWindowColor(status);
  const recommendation = context.collection_recommendation;

  if (recommendation === 'sar_recommended' || status === 'poor') {
    const hours =
      context.poor_optical_hours && context.poor_optical_hours >= 24
        ? ` (${context.poor_optical_hours}h+ heavy cloud)`
        : '';
    return {
      status: 'poor',
      headline: 'SAR RECOMMENDED',
      detail: context.collection_badge || `Optical collection poor${hours}`,
      color,
      sarRecommended: true,
    };
  }

  if (recommendation === 'optical_limited' || status === 'fair') {
    return {
      status: 'fair',
      headline: 'OPTICAL LIMITED',
      detail: context.optical_summary || context.collection_badge || 'Check forecast window',
      color,
      sarRecommended: false,
    };
  }

  if (recommendation === 'optical_ok' || status === 'good') {
    return {
      status: 'good',
      headline: 'OPTICAL CLEAR',
      detail: context.collection_badge || 'Sentinel-2 / optical collection viable',
      color,
      sarRecommended: false,
    };
  }

  return null;
}

export function buildCollectionPlanner(
  weather?: PointWeather | null,
): CollectionPlannerBadge | null {
  if (!weather || weather.error) return null;

  const optical = weather.optical_window;
  const status = optical?.status ?? 'unknown';
  const color = opticalWindowColor(status);
  const poorHours = poorOpticalHours(weather.hourly_next_48h);

  if (status === 'poor') {
    const hoursLabel = poorHours >= 24 ? ` (${poorHours}h+ heavy cloud)` : '';
    return {
      status,
      headline: 'SAR RECOMMENDED',
      detail: `Optical collection poor${hoursLabel} — use Sentinel-1 / SAR passes`,
      color,
      sarRecommended: true,
    };
  }

  if (status === 'fair') {
    return {
      status,
      headline: 'OPTICAL LIMITED',
      detail: optical?.summary ?? 'Check forecast for clearest window',
      color,
      sarRecommended: false,
    };
  }

  if (status === 'good') {
    return {
      status,
      headline: 'OPTICAL CLEAR',
      detail: 'Sentinel-2 / optical collection viable now',
      color,
      sarRecommended: false,
    };
  }

  return {
    status: 'unknown',
    headline: 'COLLECTION PLANNER',
    detail: 'Assess local cloud cover before optical tasking',
    color,
    sarRecommended: false,
  };
}