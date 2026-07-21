/** Nash / Deterrence client + types for Strategic Analysis panel. */

import { API_BASE } from '@/lib/api';

export interface StrategicDeterrence {
  score: number;
  band: 'strong' | 'contested' | 'fragile' | string;
  avg_gt_risk?: number;
  max_gt_risk?: number;
  keyword_hits?: number;
  entity_boost?: number;
}

export interface StrategicArrow {
  from: [number, number];
  to: [number, number];
  label: string;
}

export interface StrategicFlashpoint {
  id: string;
  label: string;
  lat?: number;
  lng?: number;
  row_actor?: string;
  col_actor?: string;
  row_strategies?: string[];
  col_strategies?: string[];
  payoffs?: number[][][];
  equilibria?: number[][];
  current_row?: number;
  current_col?: number;
  locked_strategies?: boolean;
  nash_score?: number;
  nash_band?: 'stable' | 'watch' | 'unstable' | string;
  deterrence?: StrategicDeterrence;
  keyword_hits?: number;
  arrow?: StrategicArrow;
  gt_scores?: Record<string, number>;
}

export interface StrategicAnalysisPayload {
  enabled: boolean;
  timestamp?: string;
  flashpoints: StrategicFlashpoint[];
  entity_hints?: unknown[];
  flashpoint_count?: number;
  fragile_count?: number;
  unstable_count?: number;
  message?: string;
}

export interface DeltaReportResult {
  enabled?: boolean;
  skipped?: boolean;
  reason?: string;
  preview?: boolean;
  timestamp?: string;
  stamp?: string;
  digest?: string;
  markdown?: string;
  summary?: string[];
  has_meaningful_change?: boolean;
  delivery?: Record<string, unknown>;
  last?: { timestamp?: string; digest?: string; paths?: Record<string, string> } | null;
  history?: Array<{ at?: string; digest?: string }>;
}

export async function fetchStrategicAnalysis(): Promise<StrategicAnalysisPayload> {
  const res = await fetch(`${API_BASE}/api/analytics/strategic`);
  if (!res.ok) {
    return { enabled: false, flashpoints: [], message: `HTTP ${res.status}` };
  }
  return res.json();
}

export async function postEntityHint(body: {
  entity_type: string;
  entity_id: string;
  label: string;
  lat: number;
  lng: number;
  flashpoint_id?: string;
}): Promise<void> {
  await fetch(`${API_BASE}/api/analytics/strategic/entity-hint`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

export async function fetchDeltaReportStatus(): Promise<DeltaReportResult> {
  const res = await fetch(`${API_BASE}/api/analytics/delta-report`);
  if (!res.ok) return { enabled: false };
  return res.json();
}

export async function generateDeltaReport(opts: {
  force?: boolean;
  preview?: boolean;
}): Promise<DeltaReportResult> {
  const res = await fetch(`${API_BASE}/api/analytics/delta-report`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ force: !!opts.force, preview: !!opts.preview }),
  });
  if (!res.ok) {
    const text = await res.text();
    return { enabled: false, skipped: true, reason: text || `HTTP ${res.status}` };
  }
  return res.json();
}

export function nashBandClass(band?: string): string {
  switch (band) {
    case 'stable':
      return 'border-emerald-500/50 bg-emerald-950/30 text-emerald-200';
    case 'watch':
      return 'border-amber-500/50 bg-amber-950/30 text-amber-100';
    case 'unstable':
      return 'border-red-500/55 bg-red-950/35 text-red-100';
    default:
      return 'border-slate-500/40 bg-slate-950/30 text-slate-200';
  }
}

export function detBandClass(band?: string): string {
  switch (band) {
    case 'strong':
      return 'bg-emerald-500';
    case 'contested':
      return 'bg-amber-500';
    case 'fragile':
      return 'bg-red-500';
    default:
      return 'bg-slate-500';
  }
}
