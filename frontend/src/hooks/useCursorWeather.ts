import { useCallback, useEffect, useRef, useState } from 'react';
import { API_BASE } from '@/lib/api';
import type { PointWeather } from '@/types/dashboard';

const WEATHER_GRID_DECIMALS = 1;
const WEATHER_THROTTLE_MS = 2500;
const WEATHER_CACHE_SIZE = 48;

export function useCursorWeather() {
  const [cursorWeather, setCursorWeather] = useState<PointWeather | null>(null);
  const [cursorWeatherLoading, setCursorWeatherLoading] = useState(false);
  const cacheRef = useRef<Map<string, PointWeather>>(new Map());
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const lastKeyRef = useRef('');

  useEffect(() => {
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
      abortRef.current?.abort();
    };
  }, []);

  const handleCursorWeather = useCallback((coords: { lat: number; lng: number } | null) => {
    if (timerRef.current) clearTimeout(timerRef.current);
    if (!coords) {
      setCursorWeather(null);
      setCursorWeatherLoading(false);
      return;
    }

    timerRef.current = setTimeout(async () => {
      const gridKey = `${coords.lat.toFixed(WEATHER_GRID_DECIMALS)},${coords.lng.toFixed(WEATHER_GRID_DECIMALS)}`;
      if (gridKey === lastKeyRef.current) return;
      lastKeyRef.current = gridKey;

      const cached = cacheRef.current.get(gridKey);
      if (cached) {
        setCursorWeather(cached);
        setCursorWeatherLoading(false);
        return;
      }

      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      setCursorWeatherLoading(true);

      try {
        const url = `${API_BASE}/api/weather/point?lat=${coords.lat}&lng=${coords.lng}`;
        const response = await fetch(url, { signal: controller.signal });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const payload = (await response.json()) as PointWeather;
        if (controller.signal.aborted) return;

        cacheRef.current.set(gridKey, payload);
        if (cacheRef.current.size > WEATHER_CACHE_SIZE) {
          const first = cacheRef.current.keys().next().value;
          if (first) cacheRef.current.delete(first);
        }
        setCursorWeather(payload);
      } catch {
        if (!controller.signal.aborted) setCursorWeather(null);
      } finally {
        if (!controller.signal.aborted) setCursorWeatherLoading(false);
      }
    }, WEATHER_THROTTLE_MS);
  }, []);

  return { cursorWeather, cursorWeatherLoading, handleCursorWeather };
}