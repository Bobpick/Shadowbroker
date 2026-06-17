import type { GTRiskPayload } from '@/types/dashboard';
import { diversifyGtAlerts, formatGtTheaterLabel } from '@/lib/gtRegionGeo';

export interface GtAlertRow {
  region: string;
  regionLabel: string;
  risk: number;
  conflict: number;
  unrest: number;
  financial: number;
  contagion: number;
  lat: number;
  lng: number;
  score: number;
  ignition: boolean;
  risk3d?: number;
  riskDelta?: number;
  updates?: number;
  alerted3d?: boolean;
  nearbyCount?: number;
}

export function formatGtRegionLabel(region: string): string {
  return formatGtTheaterLabel(region) || 'unknown';
}

function validCoords(coords: unknown): { lat: number; lng: number } | null {
  if (!Array.isArray(coords) || coords.length < 2) return null;
  const lng = Number(coords[0]);
  const lat = Number(coords[1]);
  if (!Number.isFinite(lat) || !Number.isFinite(lng)) return null;
  if (Math.abs(lat) < 0.001 && Math.abs(lng) < 0.001) return null;
  return { lat, lng };
}

function peakScore(props: Record<string, unknown>): number {
  const composite = Number(props.risk ?? 0);
  const financial = Number(props.financial ?? 0);
  const unrest = Number(props.unrest ?? 0);
  const conflict = Number(props.conflict ?? 0);
  return Math.max(composite, financial, unrest, conflict);
}

const DEFAULT_BASE_PRIOR = 0.15;

function topAlertsMinScore(basePrior: number): number {
  return basePrior + 0.05;
}

function isAlertableRow(
  row: Pick<GtAlertRow, 'score' | 'ignition' | 'riskDelta'> & {
    alerted3d?: boolean;
  },
  basePrior: number,
): boolean {
  if (row.ignition) return true;
  if ((row.riskDelta ?? 0) >= 0.08) return true;
  if (row.alerted3d) return true;
  return row.score >= topAlertsMinScore(basePrior);
}

export function extractGtAlerts(
  payload?: GTRiskPayload | null,
  limit = 8,
): {
  alerts: GtAlertRow[];
  trackedRegions: number;
  plottedRegions: number;
  maxRegions: number;
} {
  const features = payload?.heatmap?.features || [];
  const meta = payload?.meta;
  const basePrior = Number(meta?.base_prior ?? DEFAULT_BASE_PRIOR);
  const rows: GtAlertRow[] = [];

  for (const feature of features) {
    const coords = validCoords(feature.geometry?.coordinates);
    if (!coords) continue;
    const props = (feature.properties || {}) as Record<string, unknown>;
    const region = String(props.region || '').trim().toLowerCase();
    if (!region) continue;
    rows.push({
      region,
      regionLabel: formatGtRegionLabel(region),
      risk: Number(props.risk ?? 0),
      financial: Number(props.financial ?? 0),
      unrest: Number(props.unrest ?? 0),
      conflict: Number(props.conflict ?? 0),
      contagion: Number(props.contagion ?? 0),
      lat: coords.lat,
      lng: coords.lng,
      score: peakScore(props),
      ignition: Boolean(props.micro_ignition),
      risk3d: props.risk_3d_avg != null ? Number(props.risk_3d_avg) : undefined,
      riskDelta: props.risk_delta != null ? Number(props.risk_delta) : undefined,
      updates: props.updates != null ? Number(props.updates) : undefined,
      alerted3d: Boolean(props.alerted_3d),
    });
  }

  const alertable = rows.filter((row) => isAlertableRow(row, basePrior));
  alertable.sort((a, b) => {
    if (a.ignition !== b.ignition) return a.ignition ? -1 : 1;
    if (a.score !== b.score) return b.score - a.score;
    return (b.riskDelta ?? 0) - (a.riskDelta ?? 0);
  });

  return {
    alerts: diversifyGtAlerts(alertable, limit),
    trackedRegions: meta?.tracked_regions ?? features.length,
    plottedRegions: meta?.plotted_regions ?? rows.length,
    maxRegions: meta?.max_regions ?? 500,
  };
}