import { useCallback, useEffect, useState } from 'react';
import {
  formatTempCelsius,
  formatTempRangeCelsius,
  notifyTempUnitChanged,
  readTempUnit,
  TEMP_UNIT_EVENT,
  type TempUnit,
  writeTempUnit,
} from '@/lib/temperatureUnit';

export function useTemperatureUnit() {
  const [unit, setUnitState] = useState<TempUnit>('C');

  useEffect(() => {
    setUnitState(readTempUnit());
    const onChange = () => setUnitState(readTempUnit());
    window.addEventListener(TEMP_UNIT_EVENT, onChange);
    return () => window.removeEventListener(TEMP_UNIT_EVENT, onChange);
  }, []);

  const setUnit = useCallback((next: TempUnit) => {
    writeTempUnit(next);
    notifyTempUnitChanged();
    setUnitState(next);
  }, []);

  const formatTemp = useCallback(
    (celsius: number | null | undefined) => formatTempCelsius(celsius, unit),
    [unit],
  );

  const formatTempRange = useCallback(
    (minC: number | null | undefined, maxC: number | null | undefined) =>
      formatTempRangeCelsius(minC, maxC, unit),
    [unit],
  );

  return { unit, setUnit, formatTemp, formatTempRange };
}