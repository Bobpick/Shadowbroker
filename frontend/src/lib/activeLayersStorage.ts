import type { ActiveLayers } from '@/types/dashboard';

export const ACTIVE_LAYERS_STORAGE_KEY = 'sb_active_layers';

export const DEFAULT_ACTIVE_LAYERS: ActiveLayers = {
  // Aircraft — all ON
  flights: true,
  private: true,
  jets: true,
  military: true,
  tracked: true,
  gps_jamming: true,
  // Maritime — all ON
  ships_military: true,
  ships_cargo: true,
  ships_civilian: true,
  ships_passenger: true,
  ships_tracked_yachts: true,
  fishing_activity: true,
  // Space — only satellites
  satellites: true,
  gibs_imagery: false,
  highres_satellite: false,
  sentinel_hub: false,
  viirs_nightlights: false,
  road_corridor_trends: false,
  malware_c2: false,
  submarine_cables: false,
  scm_suppliers: false,
  cyber_threats: false,
  telegram_osint: true,
  // Hazards — no fire, rest ON
  earthquakes: true,
  firms: false,
  ukraine_alerts: true,
  weather_alerts: true,
  volcanoes: true,
  air_quality: true,
  // Infrastructure — military bases + internet outages only
  cctv: false,
  datacenters: false,
  internet_outages: true,
  power_plants: false,
  military_bases: true,
  trains: false,
  // SIGINT — all ON except HF digital spots
  kiwisdr: true,
  psk_reporter: false,
  satnogs: true,
  tinygs: true,
  scanners: true,
  sigint_meshtastic: true,
  sigint_aprs: true,
  // Overlays
  ukraine_frontline: true,
  global_incidents: true,
  day_night: true,
  correlations: true,
  contradictions: true,
  uap_sightings: true,
  // Biosurveillance
  wastewater: true,
  // CrowdThreat is operator opt-in only.
  crowdthreat: false,
  gt_risk: true,
  // Shodan
  shodan_overlay: false,
  // AI Intel
  ai_intel: true,
  // SAR (Synthetic Aperture Radar)
  sar: true,
};

const ACTIVE_LAYER_KEYS = Object.keys(DEFAULT_ACTIVE_LAYERS) as Array<keyof ActiveLayers>;

export function mergeActiveLayers(
  saved: Partial<ActiveLayers> | null | undefined,
  defaults: ActiveLayers = DEFAULT_ACTIVE_LAYERS,
): ActiveLayers {
  const merged = { ...defaults };
  if (!saved || typeof saved !== 'object') return merged;
  for (const key of ACTIVE_LAYER_KEYS) {
    const value = saved[key];
    if (typeof value === 'boolean') {
      merged[key] = value;
    }
  }
  return merged;
}

export function loadActiveLayersFromStorage(
  storage: Pick<Storage, 'getItem'> = localStorage,
): ActiveLayers | null {
  try {
    const raw = storage.getItem(ACTIVE_LAYERS_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<ActiveLayers>;
    return mergeActiveLayers(parsed);
  } catch {
    return null;
  }
}

export function saveActiveLayersToStorage(
  layers: ActiveLayers,
  storage: Pick<Storage, 'setItem'> = localStorage,
): void {
  try {
    storage.setItem(ACTIVE_LAYERS_STORAGE_KEY, JSON.stringify(layers));
  } catch {
    // Ignore quota/private-mode failures.
  }
}