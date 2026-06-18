import {
  celsiusToFahrenheit,
  formatTempCelsius,
  formatTempRangeCelsius,
  readTempUnit,
  writeTempUnit,
} from '@/lib/temperatureUnit';

describe('temperatureUnit', () => {
  const storage = new Map<string, string>();

  beforeEach(() => {
    storage.clear();
  });

  const mockStorage = {
    getItem: (key: string) => storage.get(key) ?? null,
    setItem: (key: string, value: string) => {
      storage.set(key, value);
    },
  };

  it('formats Celsius and Fahrenheit', () => {
    expect(formatTempCelsius(14, 'C')).toBe('14°C');
    expect(formatTempCelsius(14, 'F')).toBe('57°F');
    expect(celsiusToFahrenheit(0)).toBe(32);
  });

  it('formats temperature ranges', () => {
    expect(formatTempRangeCelsius(10, 20, 'C')).toBe('10–20°C');
    expect(formatTempRangeCelsius(10, 20, 'F')).toBe('50–68°F');
  });

  it('persists unit preference', () => {
    expect(readTempUnit(mockStorage)).toBe('C');
    writeTempUnit('F', mockStorage);
    expect(readTempUnit(mockStorage)).toBe('F');
  });
});