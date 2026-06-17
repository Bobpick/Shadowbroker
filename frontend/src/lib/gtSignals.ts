import type { GtDossierSignalEntry } from '@/types/dashboard';

export interface ConsolidatedCostlySignal {
  signalKey: string;
  label: string;
  count: number;
  sources: string[];
  latestTimestamp?: string;
}

export function formatCostlySignalLabel(name: string): string {
  return String(name || '')
    .trim()
    .replace(/_/g, ' ')
    .toUpperCase();
}

export function consolidateCostlySignals(
  entries: GtDossierSignalEntry[],
  limit = 4,
): ConsolidatedCostlySignal[] {
  const buckets = new Map<
    string,
    { count: number; sources: Set<string>; latestTimestamp?: string }
  >();

  for (const entry of entries) {
    const keys = Object.keys(entry.signals || {});
    const signalKeys = keys.length > 0 ? keys : [entry.domain];
    for (const rawKey of signalKeys) {
      const signalKey = String(rawKey || '').trim().toLowerCase();
      if (!signalKey) continue;
      const bucket = buckets.get(signalKey) ?? { count: 0, sources: new Set<string>() };
      bucket.count += 1;
      if (entry.source) bucket.sources.add(entry.source);
      if (entry.timestamp) {
        if (!bucket.latestTimestamp || entry.timestamp > bucket.latestTimestamp) {
          bucket.latestTimestamp = entry.timestamp;
        }
      }
      buckets.set(signalKey, bucket);
    }
  }

  return [...buckets.entries()]
    .map(([signalKey, bucket]) => ({
      signalKey,
      label: formatCostlySignalLabel(signalKey),
      count: bucket.count,
      sources: [...bucket.sources],
      latestTimestamp: bucket.latestTimestamp,
    }))
    .sort((a, b) => {
      if (b.count !== a.count) return b.count - a.count;
      return String(b.latestTimestamp || '').localeCompare(String(a.latestTimestamp || ''));
    })
    .slice(0, limit);
}

export function formatConsolidatedSources(sources: string[], maxShown = 2): string {
  if (!sources.length) return '';
  if (sources.length <= maxShown) return sources.join(' · ');
  const shown = sources.slice(0, maxShown).join(' · ');
  return `${shown} +${sources.length - maxShown}`;
}