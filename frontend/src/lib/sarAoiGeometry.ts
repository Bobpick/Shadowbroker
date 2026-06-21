import type { SarAoi } from '@/types/dashboard';

export function haversineKm(lat1: number, lon1: number, lat2: number, lon2: number): number {
  const r = 6371;
  const p1 = (lat1 * Math.PI) / 180;
  const p2 = (lat2 * Math.PI) / 180;
  const dp = ((lat2 - lat1) * Math.PI) / 180;
  const dl = ((lon2 - lon1) * Math.PI) / 180;
  const a =
    Math.sin(dp / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) ** 2;
  return 2 * r * Math.asin(Math.sqrt(a));
}

export function pointInAoi(lat: number, lon: number, aoi: SarAoi): boolean {
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) return false;
  const [centerLat, centerLon] = aoi.center;
  return haversineKm(lat, lon, centerLat, centerLon) <= Math.max(aoi.radius_km || 25, 1);
}

/** Place a marker inside an AOI circle (ring offset when multiple). */
export function pinInsideAoi(
  aoi: SarAoi,
  index: number,
  total: number,
): [number, number] {
  const [lat, lon] = aoi.center;
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) return [0, 0];
  if (total <= 1) return [lon, lat];

  const radiusKm = Math.min(Math.max(aoi.radius_km || 25, 1) * 0.22, 14);
  const angle = (index / total) * 2 * Math.PI;
  const kmPerDegLat = 111.32;
  const kmPerDegLon = 111.32 * Math.cos((lat * Math.PI) / 180);
  return [
    lon + (radiusKm * Math.cos(angle)) / Math.max(0.0001, kmPerDegLon),
    lat + (radiusKm * Math.sin(angle)) / kmPerDegLat,
  ];
}