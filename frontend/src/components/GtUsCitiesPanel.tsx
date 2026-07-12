'use client';

import React, { useMemo } from 'react';
import { ChevronRight, Flag } from 'lucide-react';
import { useTranslation } from '@/i18n';
import { useDataKey } from '@/hooks/useDataStore';
import { extractGtUsCities, protestPotentialLabel } from '@/lib/gtUsCities';
import { GT_ICON } from '@/lib/gtTypography';
import type { SelectedEntity } from '@/types/dashboard';

interface Props {
  layerEnabled?: boolean;
  onFlyTo?: (lat: number, lng: number) => void;
  onSelectEntity?: (entity: SelectedEntity | null) => void;
  embedded?: boolean;
}

function pct(value: number): string {
  return `${(value * 100).toFixed(0)}%`;
}

function tierClass(tier: ReturnType<typeof protestPotentialLabel>): string {
  switch (tier) {
    case 'high':
      return 'border-red-500/70 bg-red-950/35 text-red-100';
    case 'elevated':
      return 'border-red-400/55 bg-red-950/20 text-red-100';
    case 'watch':
      return 'border-blue-400/55 bg-blue-950/25 text-blue-50';
    default:
      return 'border-slate-500/40 bg-slate-950/30 text-slate-200';
  }
}

export default function GtUsCitiesPanel({
  layerEnabled = false,
  onFlyTo,
  onSelectEntity,
  embedded = false,
}: Props) {
  const { t } = useTranslation();
  const gtRisk = useDataKey('gt_risk');

  const watch = useMemo(() => extractGtUsCities(gtRisk), [gtRisk]);

  if (!layerEnabled || !watch.enabled) return null;

  const shellClass = embedded
    ? 'pointer-events-auto border-t border-blue-700/35 bg-[linear-gradient(180deg,rgba(30,58,138,0.22),rgba(15,23,42,0.92))]'
    : 'pointer-events-auto max-w-[min(92vw,34rem)] border border-blue-600/45 bg-[linear-gradient(180deg,rgba(30,58,138,0.28),rgba(2,6,23,0.94))] backdrop-blur-sm shadow-[0_0_18px_rgba(59,130,246,0.14)]';

  const handleSelect = (city: (typeof watch.cities)[number]) => {
    onFlyTo?.(city.lat, city.lng);
    onSelectEntity?.({
      id: city.city,
      type: 'gt_risk',
      name: city.label,
      extra: {
        region: city.city,
        risk: city.risk,
        unrest: city.unrest,
        financial: 0,
        conflict: 0,
        contagion: 0,
        lat: city.lat,
        lng: city.lng,
        risk_spot: city.risk,
        micro_ignition: city.ignition,
        protest_potential: city.protestPotential,
      },
    });
  };

  return (
    <div className={shellClass}>
      <div className="flex items-center gap-2 border-b border-blue-700/40 bg-[linear-gradient(90deg,rgba(185,28,28,0.35),rgba(248,250,252,0.08),rgba(29,78,216,0.35))] px-2.5 py-1.5">
        <Flag size={GT_ICON.lg} className="shrink-0 text-white" />
        <span className="text-[15px] font-mono font-bold tracking-widest text-white">
          {t('gtUsCities.title')}
        </span>
        <span className="text-[14px] font-mono tracking-wider text-blue-100/75">
          {t('gtUsCities.counts')
            .replace('{active}', String(watch.activeMetros))
            .replace('{tracked}', String(watch.trackedMetros))
            .replace('{days}', String(watch.lookbackDays))}
        </span>
      </div>

      {watch.cities.length === 0 ? (
        <div className="px-2.5 py-2 text-[15px] font-mono tracking-wider text-blue-100/65">
          {t('gtUsCities.empty')}
        </div>
      ) : (
        <div className="grid gap-1.5 px-2 py-2 sm:grid-cols-2">
          {watch.cities.map((city) => {
            const tier = protestPotentialLabel(city.protestPotential);
            return (
              <button
                key={city.city}
                type="button"
                onClick={() => handleSelect(city)}
                className={`group flex min-w-0 flex-col gap-1 border px-2 py-1.5 text-left transition-colors hover:brightness-110 ${tierClass(tier)}`}
                style={{
                  borderLeftWidth: '4px',
                  borderLeftColor:
                    tier === 'high' || tier === 'elevated'
                      ? 'rgba(239,68,68,0.85)'
                      : 'rgba(59,130,246,0.75)',
                }}
              >
                <div className="flex items-center gap-1">
                  <span className="truncate text-[15px] font-mono font-bold uppercase text-white">
                    {city.label}
                  </span>
                  {city.ignition && (
                    <span className="shrink-0 border border-red-300/60 bg-red-900/50 px-1 text-[12px] font-mono text-red-100">
                      {t('gtUsCities.ignite')}
                    </span>
                  )}
                  <ChevronRight
                    size={GT_ICON.sm}
                    className="ml-auto shrink-0 text-white/50 group-hover:text-white"
                  />
                </div>

                <div className="h-1.5 w-full overflow-hidden rounded-sm bg-slate-900/80">
                  <div
                    className="h-full bg-[linear-gradient(90deg,#dc2626,#f8fafc,#2563eb)]"
                    style={{ width: `${Math.min(100, city.protestPotential * 100)}%` }}
                  />
                </div>

                <div className="text-[14px] font-mono tracking-wide text-blue-50/85">
                  {t('gtUsCities.line')
                    .replace('{potential}', pct(city.protestPotential))
                    .replace('{unrest}', pct(city.unrest))
                    .replace('{mentions}', String(city.protestMentions))}
                </div>

                {city.mobilizationHits > 0 && (
                  <div className="text-[12px] font-mono uppercase tracking-wider text-red-100/80">
                    {t('gtUsCities.mobilization').replace(
                      '{count}',
                      String(city.mobilizationHits),
                    )}
                  </div>
                )}
              </button>
            );
          })}
        </div>
      )}

      <div className="border-t border-blue-800/30 px-2.5 py-1 text-[12px] font-mono tracking-wider text-blue-100/55">
        {t('gtUsCities.hint')}
      </div>
    </div>
  );
}