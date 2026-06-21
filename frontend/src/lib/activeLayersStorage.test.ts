import { describe, expect, it } from 'vitest';
import {
  ACTIVE_LAYERS_STORAGE_KEY,
  DEFAULT_ACTIVE_LAYERS,
  loadActiveLayersFromStorage,
  mergeActiveLayers,
  saveActiveLayersToStorage,
} from './activeLayersStorage';

describe('activeLayersStorage', () => {
  it('merges saved values over defaults and keeps new layer keys', () => {
    const merged = mergeActiveLayers({
      uap_sightings: false,
      flights: false,
      unknown_layer: true,
    } as Partial<typeof DEFAULT_ACTIVE_LAYERS>);
    expect(merged.uap_sightings).toBe(false);
    expect(merged.flights).toBe(false);
    expect(merged.telegram_osint).toBe(DEFAULT_ACTIVE_LAYERS.telegram_osint);
  });

  it('round-trips layer preferences through storage', () => {
    const storage = new Map<string, string>();
    const layers = {
      ...DEFAULT_ACTIVE_LAYERS,
      uap_sightings: false,
      wastewater: false,
      ai_intel: false,
    };

    saveActiveLayersToStorage(layers, {
      setItem: (key, value) => storage.set(key, value),
    });

    const loaded = loadActiveLayersFromStorage({
      getItem: (key) => storage.get(key) ?? null,
    });

    expect(storage.get(ACTIVE_LAYERS_STORAGE_KEY)).toBeTruthy();
    expect(loaded?.uap_sightings).toBe(false);
    expect(loaded?.wastewater).toBe(false);
    expect(loaded?.ai_intel).toBe(false);
    expect(loaded?.flights).toBe(DEFAULT_ACTIVE_LAYERS.flights);
  });

  it('returns null for invalid stored JSON', () => {
    const loaded = loadActiveLayersFromStorage({
      getItem: () => '{not-json',
    });
    expect(loaded).toBeNull();
  });
});