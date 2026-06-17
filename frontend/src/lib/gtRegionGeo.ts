/** Geographic helpers for GT alert display — mirrors backend/analytics/region_geo.py */

const THEATER_LABELS: Record<string, string> = {
  ukraine: 'Ukraine',
  russia: 'Russia',
  israel: 'Israel',
  gaza: 'Gaza',
  iran: 'Iran',
  syria: 'Syria',
  taiwan: 'Taiwan',
  china: 'China',
  global: 'Global',
};

export function formatGtTheaterLabel(region: string): string {
  const key = String(region || '').trim().toLowerCase();
  if (THEATER_LABELS[key]) return THEATER_LABELS[key];
  const coord = key.match(/^(-?\d+(?:\.\d+)?),\s*(-?\d+(?:\.\d+)?)$/);
  if (coord) {
    return `${Number(coord[1]).toFixed(1)}°, ${Number(coord[2]).toFixed(1)}°`;
  }
  return key.replace(/_/g, ' ').replace(/\b\w/g, (ch) => ch.toUpperCase());
}

function haversineKm(lat1: number, lng1: number, lat2: number, lng2: number): number {
  const radiusKm = 6371;
  const phi1 = (lat1 * Math.PI) / 180;
  const phi2 = (lat2 * Math.PI) / 180;
  const dphi = ((lat2 - lat1) * Math.PI) / 180;
  const dlambda = ((lng2 - lng1) * Math.PI) / 180;
  const a =
    Math.sin(dphi / 2) ** 2 +
    Math.cos(phi1) * Math.cos(phi2) * Math.sin(dlambda / 2) ** 2;
  return 2 * radiusKm * Math.asin(Math.sqrt(Math.min(1, a)));
}

export function diversifyGtAlerts<T extends { lat: number; lng: number }>(
  rows: T[],
  limit: number,
  minSeparationKm = 160,
): Array<T & { nearbyCount?: number }> {
  if (!rows.length) return [];

  const selected: Array<T & { nearbyCount?: number }> = [];
  const used = new Set<number>();

  for (let idx = 0; idx < rows.length && selected.length < limit; idx += 1) {
    const row = rows[idx];
    const tooClose = selected.some(
      (pick) => haversineKm(row.lat, row.lng, pick.lat, pick.lng) < minSeparationKm,
    );
    if (tooClose) continue;

    let nearby = 1;
    for (let j = 0; j < rows.length; j += 1) {
      if (j === idx) continue;
      if (haversineKm(row.lat, row.lng, rows[j].lat, rows[j].lng) < minSeparationKm) {
        nearby += 1;
      }
    }
    selected.push(nearby > 1 ? { ...row, nearbyCount: nearby } : { ...row });
    used.add(idx);
  }

  if (selected.length < limit) {
    for (let idx = 0; idx < rows.length && selected.length < limit; idx += 1) {
      if (used.has(idx)) continue;
      selected.push({ ...rows[idx] });
      used.add(idx);
    }
  }

  return selected.slice(0, limit);
}