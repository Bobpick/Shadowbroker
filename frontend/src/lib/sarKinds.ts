export type SarKindFilter = 'excavation' | 'water' | 'all';

export const SAR_KIND_FILTER_STORAGE_KEY = 'sb_sar_kind_filter';

export const SAR_EXCAVATION_KINDS = new Set([
  'ground_deformation',
  'vegetation_disturbance',
  'coherence_change',
  'damage_assessment',
]);

export const SAR_WATER_KINDS = new Set(['surface_water_change', 'flood_extent']);

function defaultStorage(): Storage | null {
  if (typeof window === 'undefined') return null;
  return window.localStorage;
}

export function readSarKindFilter(storage?: Pick<Storage, 'getItem'> | null): SarKindFilter {
  try {
    const store = storage ?? defaultStorage();
    if (!store) return 'excavation';
    const value = store.getItem(SAR_KIND_FILTER_STORAGE_KEY);
    if (value === 'water' || value === 'all') return value;
  } catch {
    // ignore
  }
  return 'excavation';
}

export function writeSarKindFilter(
  filter: SarKindFilter,
  storage?: Pick<Storage, 'setItem'> | null,
): void {
  try {
    const store = storage ?? defaultStorage();
    if (!store) return;
    store.setItem(SAR_KIND_FILTER_STORAGE_KEY, filter);
  } catch {
    // ignore
  }
}

export function matchesSarKindFilter(kind: string, filter: SarKindFilter): boolean {
  if (filter === 'all') return true;
  if (filter === 'water') return SAR_WATER_KINDS.has(kind);
  return SAR_EXCAVATION_KINDS.has(kind);
}

export function sarKindLabel(kind: string): string {
  switch (kind) {
    case 'ground_deformation':
      return 'Ground subsidence (InSAR) — excavation / tunneling / collapse';
    case 'vegetation_disturbance':
      return 'Land clearance — excavation, grading, or construction';
    case 'coherence_change':
      return 'Surface change — earth moved or structures altered';
    case 'damage_assessment':
      return 'Damage assessment — structural disruption';
    case 'surface_water_change':
      return 'Surface water / wetness change (not excavation)';
    case 'flood_extent':
      return 'Flood extent';
    case 'scene_pass':
      return 'Sentinel-1 pass catalog';
    default:
      return kind.replace(/_/g, ' ');
  }
}