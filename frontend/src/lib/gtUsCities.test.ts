import { describe, expect, it } from 'vitest';
import {
  NYC_METRO_KEY,
  personalPlanningGuidanceKey,
  protestPotentialDriver,
  protestPotentialLabel,
  type GtUsCityRow,
} from '@/lib/gtUsCities';

function city(overrides: Partial<GtUsCityRow> = {}): GtUsCityRow {
  return {
    city: NYC_METRO_KEY,
    label: 'New York City',
    lat: 40.712,
    lng: -74.006,
    protestPotential: 0.43,
    unrest: 0.34,
    risk: 0.3,
    ignition: false,
    mentions: 2,
    protestMentions: 0,
    mobilizationHits: 0,
    sources: [],
    recentSignals: [],
    ...overrides,
  };
}

describe('protestPotentialLabel', () => {
  it('maps score bands to tiers', () => {
    expect(protestPotentialLabel(0.1)).toBe('low');
    expect(protestPotentialLabel(0.2)).toBe('watch');
    expect(protestPotentialLabel(0.43)).toBe('elevated');
    expect(protestPotentialLabel(0.55)).toBe('high');
  });
});

describe('protestPotentialDriver', () => {
  it('marks DC-style metros feed-driven when protest hits dominate', () => {
    expect(
      protestPotentialDriver(
        city({ unrest: 0.32, protestMentions: 25, protestPotential: 0.54 }),
      ),
    ).toBe('feed');
  });

  it('marks NYC-style metros gt-driven without protest hits', () => {
    expect(
      protestPotentialDriver(
        city({ unrest: 0.34, protestMentions: 0, mentions: 0, protestPotential: 0.54 }),
      ),
    ).toBe('gt');
  });
});

describe('personalPlanningGuidanceKey', () => {
  it('returns elevatedQuiet for Brooklyn-style elevated scores without feed hits', () => {
    expect(personalPlanningGuidanceKey(city())).toBe('elevatedQuiet');
  });

  it('returns elevatedActive when protest or mobilization chatter appears', () => {
    expect(personalPlanningGuidanceKey(city({ protestMentions: 2 }))).toBe('elevatedActive');
    expect(personalPlanningGuidanceKey(city({ mobilizationHits: 1 }))).toBe('elevatedActive');
  });

  it('returns considerRelocation for high scores with mobilization or ignition', () => {
    expect(personalPlanningGuidanceKey(city({ protestPotential: 0.6, mobilizationHits: 2 }))).toBe(
      'considerRelocation',
    );
    expect(personalPlanningGuidanceKey(city({ protestPotential: 0.58, ignition: true }))).toBe(
      'considerRelocation',
    );
  });
});