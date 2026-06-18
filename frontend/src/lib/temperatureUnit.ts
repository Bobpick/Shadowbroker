export type TempUnit = 'C' | 'F';

export const TEMP_UNIT_STORAGE_KEY = 'sb_temp_unit';
export const TEMP_UNIT_EVENT = 'sb:temp-unit-changed';

export function celsiusToFahrenheit(celsius: number): number {
  return (celsius * 9) / 5 + 32;
}

export function formatTempCelsius(
  celsius: number | null | undefined,
  unit: TempUnit,
): string {
  if (celsius == null || Number.isNaN(celsius)) return '—';
  if (unit === 'F') return `${celsiusToFahrenheit(celsius).toFixed(0)}°F`;
  return `${celsius.toFixed(0)}°C`;
}

export function formatTempRangeCelsius(
  minC: number | null | undefined,
  maxC: number | null | undefined,
  unit: TempUnit,
): string {
  if (minC == null || maxC == null || Number.isNaN(minC) || Number.isNaN(maxC)) {
    return '—';
  }
  if (unit === 'F') {
    return `${celsiusToFahrenheit(minC).toFixed(0)}–${celsiusToFahrenheit(maxC).toFixed(0)}°F`;
  }
  return `${minC.toFixed(0)}–${maxC.toFixed(0)}°C`;
}

export function readTempUnit(storage: Pick<Storage, 'getItem'> = localStorage): TempUnit {
  try {
    return storage.getItem(TEMP_UNIT_STORAGE_KEY) === 'F' ? 'F' : 'C';
  } catch {
    return 'C';
  }
}

export function writeTempUnit(
  unit: TempUnit,
  storage: Pick<Storage, 'setItem'> = localStorage,
): void {
  try {
    storage.setItem(TEMP_UNIT_STORAGE_KEY, unit);
  } catch {
    // localStorage unavailable
  }
}

export function notifyTempUnitChanged(): void {
  if (typeof window === 'undefined') return;
  window.dispatchEvent(new Event(TEMP_UNIT_EVENT));
}