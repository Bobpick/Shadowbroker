import type { WeatherForecastMeta } from '@/types/dashboard';

const OM_HOST = 'https://map-tiles.open-meteo.com/data_spatial/dwd_icon';

let _protocolRegistered = false;
let _omRequestChain: Promise<unknown> = Promise.resolve();

type OmProtocolHandler = (
  params: { url: string; type?: string },
  abortController?: AbortController,
) => Promise<{ data: ArrayBuffer | null | undefined }>;

async function loadOmProtocol(): Promise<OmProtocolHandler> {
  const { omProtocol } = await import('@openmeteo/weather-map-layer');
  return omProtocol as OmProtocolHandler;
}

function isBenignOmError(err: unknown): boolean {
  const msg = err instanceof Error ? err.message : String(err);
  return (
    msg.includes('Reader not initialized') ||
    msg.includes('Aborted') ||
    msg.includes('abort')
  );
}

export function registerOpenMeteoProtocol(maplibregl: {
  addProtocol: (
    name: string,
    handler: (
      params: { url: string },
      abortController?: AbortController,
    ) => Promise<{ data: ArrayBuffer }>,
  ) => void;
}): void {
  if (typeof window === 'undefined') return;
  if (_protocolRegistered) return;
  _protocolRegistered = true;

  const emptyTile = new ArrayBuffer(0);

  maplibregl.addProtocol('om', (params, abortController) => {
    const run = _omRequestChain.then(async () => {
      try {
        const protocol = await loadOmProtocol();
        return await protocol(params, abortController);
      } catch (err) {
        if (abortController?.signal.aborted || isBenignOmError(err)) {
          return { data: emptyTile };
        }
        throw err;
      }
    });
    _omRequestChain = run.catch(() => undefined);
    return run as Promise<{ data: ArrayBuffer }>;
  });
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