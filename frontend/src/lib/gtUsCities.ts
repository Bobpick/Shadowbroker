/** US metro protest watch — reads from gt_risk.us_cities snapshot. */

import type { GTRiskPayload } from '@/types/dashboard';

export interface GtUsCitySignal {
  title: string;
  source: string;
  published?: string | null;
  link?: string | null;
}

export interface GtUsCityRow {
  city: string;
  label: string;
  lat: number;
  lng: number;
  protestPotential: number;
  unrest: number;
  risk: number;
  ignition: boolean;
  mentions: number;
  protestMentions: number;
  mobilizationHits: number;
  sources: string[];
  recentSignals: GtUsCitySignal[];
}

export interface GtUsCityWatch {
  enabled: boolean;
  cities: GtUsCityRow[];
  activeMetros: number;
  trackedMetros: number;
  lookbackDays: number;
  timestamp: string | null;
}

function toNumber(value: unknown, fallback = 0): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function mapCity(raw: Record<string, unknown>): GtUsCityRow {
  const recent = Array.isArray(raw.recent_signals) ? raw.recent_signals : [];
  return {
    city: String(raw.city || ''),
    label: String(raw.label || raw.city || ''),
    lat: toNumber(raw.lat),
    lng: toNumber(raw.lng),
    protestPotential: toNumber(raw.protest_potential),
    unrest: toNumber(raw.unrest),
    risk: toNumber(raw.risk),
    ignition: Boolean(raw.ignition),
    mentions: toNumber(raw.mentions),
    protestMentions: toNumber(raw.protest_mentions),
    mobilizationHits: toNumber(raw.mobilization_hits),
    sources: Array.isArray(raw.sources) ? raw.sources.map((s) => String(s)) : [],
    recentSignals: recent
      .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object')
      .map((item) => ({
        title: String(item.title || ''),
        source: String(item.source || ''),
        published: item.published != null ? String(item.published) : null,
        link: item.link != null ? String(item.link) : null,
      })),
  };
}

export function extractGtUsCities(gtRisk: GTRiskPayload | null | undefined): GtUsCityWatch {
  if (!gtRisk?.enabled) {
    return {
      enabled: false,
      cities: [],
      activeMetros: 0,
      trackedMetros: 0,
      lookbackDays: 7,
      timestamp: null,
    };
  }

  const payload = gtRisk?.us_cities;
  if (!payload || typeof payload !== 'object') {
    return {
      enabled: true,
      cities: [],
      activeMetros: 0,
      trackedMetros: 39,
      lookbackDays: 7,
      timestamp: gtRisk.timestamp ?? null,
    };
  }

  const raw = payload as Record<string, unknown>;
  const cities = Array.isArray(raw.cities)
    ? raw.cities
        .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object')
        .map(mapCity)
    : [];

  return {
    enabled: true,
    cities,
    activeMetros: toNumber(raw.active_metros, cities.length),
    trackedMetros: toNumber(raw.tracked_metros, 40),
    lookbackDays: toNumber(raw.lookback_days, 7),
    timestamp: raw.timestamp != null ? String(raw.timestamp) : gtRisk.timestamp ?? null,
  };
}

export function protestPotentialLabel(score: number): 'low' | 'watch' | 'elevated' | 'high' {
  if (score >= 0.55) return 'high';
  if (score >= 0.35) return 'elevated';
  if (score >= 0.18) return 'watch';
  return 'low';
}

const GT_LAYER_WEIGHT = 0.62;
const FEED_LAYER_WEIGHT = 0.38;
const DRIVER_MIXED_DELTA = 0.05;

export interface ProtestPotentialComponents {
  feedScore: number;
  protestFeedScore: number;
  gtScore: number;
  feedContribution: number;
  gtContribution: number;
}

function protestFeedScore(city: GtUsCityRow): number {
  return Math.min(1, city.protestMentions * 0.18 + city.mobilizationHits * 0.28);
}

/** Mirrors backend analytics/us_cities._protest_potential layer math. */
export function computeProtestPotentialComponents(city: GtUsCityRow): ProtestPotentialComponents {
  const protestFeed = protestFeedScore(city);
  const feedScore = Math.min(1, protestFeed + city.mentions * 0.06);
  const gtScore = Math.min(
    1,
    city.unrest * 0.55 + city.risk * 0.25 + (city.ignition ? 0.12 : 0),
  );
  return {
    feedScore,
    protestFeedScore: protestFeed,
    gtScore,
    feedContribution: feedScore * FEED_LAYER_WEIGHT,
    gtContribution: gtScore * GT_LAYER_WEIGHT,
  };
}

export function protestPotentialDriver(city: GtUsCityRow): 'feed' | 'gt' | 'mixed' {
  const { gtScore } = computeProtestPotentialComponents(city);
  const confirmedFeed = protestFeedScore(city);

  // Badge reflects confirmed protest/mobilization posts — not generic city-name mentions.
  if (city.protestMentions + city.mobilizationHits === 0) {
    return 'gt';
  }

  const gtContribution = gtScore * GT_LAYER_WEIGHT;
  const protestFeedContribution = confirmedFeed * FEED_LAYER_WEIGHT;
  const delta = Math.abs(protestFeedContribution - gtContribution);
  if (delta < DRIVER_MIXED_DELTA) return 'mixed';
  return protestFeedContribution > gtContribution ? 'feed' : 'gt';
}

/** i18n key suffix under gtUsCities.personalPlanning.guidance.* */
export function personalPlanningGuidanceKey(city: GtUsCityRow): string {
  const tier = protestPotentialLabel(city.protestPotential);
  const hasFeedSignal = city.protestMentions > 0 || city.mobilizationHits > 0;

  if (tier === 'high') {
    if (city.mobilizationHits > 0 || city.ignition) return 'considerRelocation';
    return 'highMonitor';
  }
  if (tier === 'elevated') {
    return hasFeedSignal ? 'elevatedActive' : 'elevatedQuiet';
  }
  if (tier === 'watch') return 'watch';
  return 'routine';
}

export const NYC_METRO_KEY = 'new_york';