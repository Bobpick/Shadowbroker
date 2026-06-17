import { describe, expect, it } from 'vitest';
import { consolidateCostlySignals } from '@/lib/gtSignals';
import type { GtDossierSignalEntry } from '@/types/dashboard';

describe('consolidateCostlySignals', () => {
  it('groups duplicate signal types with counts', () => {
    const entries: GtDossierSignalEntry[] = [
      {
        timestamp: '2026-06-17T12:01:00Z',
        domain: 'unrest',
        signals: { protest_mobilize: 1 },
        strength: 1,
        posterior: 0.4,
        source: 't.me/war_monitor',
        deviation_score: 0.1,
      },
      {
        timestamp: '2026-06-17T12:01:00Z',
        domain: 'unrest',
        signals: { protest_mobilize: 1 },
        strength: 1,
        posterior: 0.42,
        source: 't.me/osintdefender',
        deviation_score: 0.1,
      },
      {
        timestamp: '2026-06-17T12:01:00Z',
        domain: 'financial',
        signals: { sanctions_escalation: 1 },
        strength: 1,
        posterior: 0.45,
        source: 't.me/nexta_live',
        deviation_score: 0.1,
      },
      {
        timestamp: '2026-06-17T12:01:00Z',
        domain: 'unrest',
        signals: { protest_mobilize: 1 },
        strength: 1,
        posterior: 0.43,
        source: 't.me/war_monitor',
        deviation_score: 0.1,
      },
    ];

    const consolidated = consolidateCostlySignals(entries);
    expect(consolidated[0]).toMatchObject({
      signalKey: 'protest_mobilize',
      label: 'PROTEST MOBILIZE',
      count: 3,
    });
    expect(consolidated[1]).toMatchObject({
      signalKey: 'sanctions_escalation',
      count: 1,
    });
  });
});