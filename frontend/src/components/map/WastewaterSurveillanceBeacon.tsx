'use client';

import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Marker, Popup } from 'react-map-gl/maplibre';
import type { WastewaterSurveillanceSummary } from '@/types/dashboard';

const AUTO_EXPAND_MS = 9000;
const SESSION_SIGNATURE_KEY = 'sb_ww_beacon_signature';
// ~½" screen nudge west — clears the news marker at the US geographic center.
const BEACON_SCREEN_OFFSET: [number, number] = [-48, 0];

interface Props {
  enabled: boolean;
  surveillance?: WastewaterSurveillanceSummary | null;
}

function BiohazardIcon({ size = 28, className = '' }: { size?: number; className?: string }) {
  return (
    <svg
      viewBox="0 0 64 64"
      width={size}
      height={size}
      className={className}
      aria-hidden="true"
    >
      <circle cx="32" cy="32" r="30" fill="currentColor" opacity="0.18" />
      <g fill="none" stroke="currentColor" strokeWidth="4" strokeLinecap="round">
        <circle cx="32" cy="20" r="6" />
        <circle cx="20" cy="40" r="6" />
        <circle cx="44" cy="40" r="6" />
        <path d="M32 26v8M24 36l5-4M40 36l-5-4" />
      </g>
    </svg>
  );
}

function formatRate(display?: string, pct?: number | null): string {
  if (display) return display;
  if (pct == null || Number.isNaN(pct)) return 'n/a';
  const sign = pct > 0 ? '+' : '';
  return `${sign}${pct.toFixed(1)}%`;
}

export function WastewaterSurveillanceBeacon({ enabled, surveillance }: Props) {
  const [expanded, setExpanded] = useState(false);
  const pinnedOpenRef = useRef(false);
  const autoTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const summary = surveillance ?? {
    marker: { lat: 39.8283, lng: -98.5795 },
    rising_pathogens: [],
    pathogens_rising: 0,
    signature: '',
    plants_active: 0,
    pathogens_tracked: 0,
  };

  const marker = summary.marker;
  const rising = summary.rising_pathogens ?? [];
  const risingCount = summary.pathogens_rising ?? rising.length;
  const signature = summary.signature ?? '';
  const hasSignal = risingCount > 0;

  const lat = marker?.lat ?? 39.8283;
  const lng = marker?.lng ?? -98.5795;

  const severityClass = useMemo(() => {
    if (!hasSignal) return 'text-lime-400';
    if (risingCount >= 4) return 'text-red-400';
    if (risingCount >= 2) return 'text-amber-400';
    return 'text-yellow-300';
  }, [hasSignal, risingCount]);

  useEffect(() => {
    if (!enabled || !hasSignal || !signature) return;

    const previous = sessionStorage.getItem(SESSION_SIGNATURE_KEY);
    if (previous === signature) return;

    sessionStorage.setItem(SESSION_SIGNATURE_KEY, signature);
    pinnedOpenRef.current = false;
    setExpanded(true);

    if (autoTimerRef.current) clearTimeout(autoTimerRef.current);
    autoTimerRef.current = setTimeout(() => {
      if (!pinnedOpenRef.current) setExpanded(false);
    }, AUTO_EXPAND_MS);

    return () => {
      if (autoTimerRef.current) clearTimeout(autoTimerRef.current);
    };
  }, [enabled, hasSignal, signature]);

  if (!enabled) return null;

  const handleToggle = () => {
    if (expanded) {
      pinnedOpenRef.current = false;
      setExpanded(false);
      return;
    }
    pinnedOpenRef.current = true;
    setExpanded(true);
  };

  const dotSize = hasSignal ? 22 : 16;

  return (
    <>
      <Marker
        longitude={lng}
        latitude={lat}
        anchor="center"
        offset={BEACON_SCREEN_OFFSET}
        style={{ zIndex: 12 }}
      >
        <button
          type="button"
          onClick={handleToggle}
          className={`group flex items-center justify-center rounded-full border shadow-[0_0_18px_rgba(190,242,100,0.35)] transition-transform hover:scale-110 ${
            hasSignal
              ? 'border-lime-400/70 bg-black/85 animate-pulse'
              : 'border-lime-700/50 bg-black/70'
          }`}
          style={{ width: dotSize, height: dotSize }}
          title={
            hasSignal
              ? `${risingCount} pathogen(s) rising in wastewater surveillance`
              : 'Wastewater biosurveillance nominal'
          }
        >
          <BiohazardIcon
            size={hasSignal ? 16 : 12}
            className={`${severityClass} drop-shadow-[0_0_6px_rgba(190,242,100,0.55)]`}
          />
        </button>
      </Marker>

      {expanded && (
        <Popup
          longitude={lng}
          latitude={lat}
          closeButton={false}
          closeOnClick={false}
          onClose={() => {
            pinnedOpenRef.current = false;
            setExpanded(false);
          }}
          anchor="top"
          offset={[BEACON_SCREEN_OFFSET[0], BEACON_SCREEN_OFFSET[1] + 18]}
          maxWidth="360px"
          className="threat-popup"
        >
          <div className="map-popup min-w-[280px] border border-lime-500/40 bg-[#08110a]/95 font-mono text-lime-100">
            <div className="mb-2 flex items-start justify-between gap-3 border-b border-lime-500/20 pb-2">
              <div>
                <div className="flex items-center gap-2 text-[11px] font-bold tracking-[0.25em] text-lime-300">
                  <BiohazardIcon size={16} className="text-lime-300" />
                  BIOSURVEILLANCE
                </div>
                <div className="mt-1 text-[10px] text-lime-500/80">
                  WastewaterSCAN · 21-day trend window
                </div>
              </div>
              <button
                type="button"
                onClick={() => {
                  pinnedOpenRef.current = false;
                  setExpanded(false);
                }}
                className="text-lime-600 transition-colors hover:text-lime-200"
                aria-label="Close biosurveillance summary"
              >
                ✕
              </button>
            </div>

            {hasSignal ? (
              <>
                <div className="mb-2 text-[10px] text-lime-400/90">
                  {risingCount} pathogen{risingCount === 1 ? '' : 's'} rising across US wastewater
                  {summary.baseline_date ? (
                    <span> · vs {summary.baseline_date}</span>
                  ) : null}
                </div>
                <div className="flex max-h-[min(50vh,280px)] flex-col gap-1.5 overflow-y-auto styled-scrollbar">
                  {rising.map((pathogen) => (
                    <div
                      key={pathogen.name}
                      className="rounded border border-lime-500/20 bg-black/50 px-2 py-1.5"
                    >
                      <div className="flex items-center justify-between gap-2 text-[11px]">
                        <span className="font-bold text-lime-200">{pathogen.name}</span>
                        <span className="text-amber-300">↑ RISING</span>
                      </div>
                      <div className="mt-1 grid grid-cols-2 gap-x-3 gap-y-0.5 text-[10px] text-lime-400/90">
                        <span>States rising: <span className="text-white">{pathogen.states_rising}</span></span>
                        <span>States elevated: <span className="text-white">{pathogen.states_alert}</span></span>
                        <span>Rate: <span className="text-white">{formatRate(pathogen.rising_rate_display, pathogen.rising_rate_pct)}</span></span>
                        <span>Δ states: <span className="text-white">{pathogen.states_rising_delta ?? 0}</span></span>
                      </div>
                    </div>
                  ))}
                </div>
              </>
            ) : (
              <div className="py-3 text-center text-[10px] text-lime-500/80">
                No rising pathogen signals in the current 21-day window.
              </div>
            )}

            <div className="mt-2 border-t border-lime-500/15 pt-2 text-[9px] text-lime-600/80">
              {summary.fetch_progress?.total ? (
                <>
                  {summary.fetch_progress.with_data ?? summary.plants_active ?? 0}/
                  {summary.fetch_progress.total} sites loaded
                  {' · '}
                  {summary.pathogens_tracked ?? 0} pathogens tracked
                </>
              ) : (
                <>
                  {summary.plants_active ?? 0} active sites · {summary.pathogens_tracked ?? 0} pathogens tracked
                </>
              )}
            </div>
          </div>
        </Popup>
      )}
    </>
  );
}