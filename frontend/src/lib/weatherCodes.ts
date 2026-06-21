const WMO_LABELS: Record<number, string> = {
  0: 'Clear',
  1: 'Mainly clear',
  2: 'Partly cloudy',
  3: 'Overcast',
  45: 'Fog',
  48: 'Rime fog',
  51: 'Light drizzle',
  53: 'Drizzle',
  55: 'Dense drizzle',
  61: 'Slight rain',
  63: 'Rain',
  65: 'Heavy rain',
  71: 'Slight snow',
  73: 'Snow',
  75: 'Heavy snow',
  80: 'Rain showers',
  81: 'Heavy showers',
  95: 'Thunderstorm',
};

export function weatherCodeLabel(code: number | null | undefined): string {
  if (code == null) return 'Unknown';
  return WMO_LABELS[code] ?? `Code ${code}`;
}

export function opticalWindowColor(status: string | undefined): string {
  switch (status) {
    case 'good':
      return '#4ade80';
    case 'fair':
      return '#fbbf24';
    case 'poor':
      return '#f87171';
    default:
      return '#94a3b8';
  }
}

export function formatWind(speedKmh: number | null | undefined, dirDeg: number | null | undefined): string {
  if (speedKmh == null) return '—';
  const dir = dirDeg != null ? `${Math.round(dirDeg)}°` : '';
  return `${Math.round(speedKmh)} km/h${dir ? ` @ ${dir}` : ''}`;
}