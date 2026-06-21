import { omProtocol } from '@openmeteo/weather-map-layer';
import type { WeatherForecastMeta } from '@/types/dashboard';

const OM_HOST = 'https://map-tiles.open-meteo.com/data_spatial/dwd_icon';

let _protocolRegistered = false;

export function registerOpenMeteoProtocol(maplibregl: {
  addProtocol: (
    name: string,
    handler: (
      params: { url: string },
      abortController?: AbortController,
    ) => Promise<{ data: ArrayBuffer }>,
  ) => void;
}): void {
  if (_protocolRegistered) return;
  _protocolRegistered = true;
  maplibregl.addProtocol(
    'om',
    omProtocol as (
      params: { url: string },
      abortController?: AbortController,
    ) => Promise<{ data: ArrayBuffer }>,
  );
}

export function buildOpenMeteoOmUrl(
  variable: 'cloud_cover' | 'precipitation',
  timeStep = 'current_time_1H',
): string {
  return `${OM_HOST}/latest.json?time_step=${timeStep}&variable=${variable}`;
}

export function openMeteoSourceUrl(
  variable: 'cloud_cover' | 'precipitation',
  timeStep = 'current_time_1H',
): string {
  return `om://${buildOpenMeteoOmUrl(variable, timeStep)}`;
}

export function pickForecastTimeStep(
  meta: WeatherForecastMeta | null | undefined,
  hourOffset = 0,
): string {
  if (!meta?.valid_times?.length || hourOffset <= 0) {
    return 'current_time_1H';
  }
  const idx = Math.min(hourOffset, meta.valid_times.length - 1);
  return `valid_times_${idx}`;
}

export const OPEN_METEO_FORECAST_STEPS = [
  { id: 'now', label: 'Now', offset: 0 },
  { id: '6h', label: '+6h', offset: 6 },
  { id: '24h', label: '+24h', offset: 24 },
] as const;