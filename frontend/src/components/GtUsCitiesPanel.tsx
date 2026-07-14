'use client';

import React, { useMemo } from 'react';
import { ChevronRight, Flag, Info } from 'lucide-react';
import { useTranslation } from '@/i18n';
import { useDataKey } from '@/hooks/useDataStore';
import {
  extractGtUsCities,
  NYC_METRO_KEY,
  personalPlanningGuidanceKey,
  protestPotentialDriver,
  protestPotentialLabel,
} from '@/lib/gtUsCities';
import { GT_ICON, GT_TEXT } from '@/lib/gtTypography';
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

function driverBadgeClass(driver: ReturnType<typeof protestPotentialDriver>): string {
  switch (driver) {
    case 'feed':
      return 'border-amber-300/55 bg-amber-950/45 text-amber-100';
    case 'gt':
      return 'border-blue-300/55 bg-blue-950/45 text-blue-100';
    default:
      return 'border-slate-300/45 bg-slate-900/45 text-slate-100';
  }
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
  const nycMetro = useMemo(
    () => watch.cities.find((city) => city.city === NYC_METRO_KEY) ?? null,
    [watch.cities],
  );

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
        <span
          className={`${GT_TEXT.xs} font-mono font-bold tracking-widest text-white`}
          title={t('gtUsCities.titleTooltip')}
        >
          {t('gtUsCities.title')}
        </span>
        <span title={t('gtUsCities.titleTooltip')} className="shrink-0 leading-none">
          <Info
            size={GT_ICON.sm}
            className="text-blue-200/70"
            aria-hidden="true"
          />
        </span>
        <span className={`${GT_TEXT.micro} font-mono tracking-wider text-blue-100/75`}>
          {t('gtUsCities.counts')
            .replace('{active}', String(watch.activeMetros))
            .replace('{tracked}', String(watch.trackedMetros))
            .replace('{days}', String(watch.lookbackDays))}
        </span>
      </div>

      {watch.cities.length === 0 ? (
        <div className={`px-2.5 py-2 ${GT_TEXT.xs} font-mono tracking-wider text-blue-100/65`}>
          {t('gtUsCities.empty')}
        </div>
      ) : (
        <div className="grid gap-1.5 px-2 py-2 sm:grid-cols-2">
          {watch.cities.map((city) => {
            const tier = protestPotentialLabel(city.protestPotential);
            const driver = protestPotentialDriver(city);
            const cardTooltip = t('gtUsCities.cardTooltip')
              .replace('{city}', city.label)
              .replace('{potential}', pct(city.protestPotential))
              .replace('{unrest}', pct(city.unrest))
              .replace('{mentions}', String(city.protestMentions));
            const protestHitsTooltip = t('gtUsCities.protestHitsTooltip').replace(
              '{days}',
              String(watch.lookbackDays),
            );
            return (
              <button
                key={city.city}
                type="button"
                onClick={() => handleSelect(city)}
                title={cardTooltip}
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
                  <span className={`truncate ${GT_TEXT.xs} font-mono font-bold uppercase text-white`}>
                    {city.label}
                  </span>
                  <span
                    className={`shrink-0 border px-1 text-[9px] font-mono font-bold tracking-wider ${driverBadgeClass(driver)}`}
                    title={t(`gtUsCities.driver.${driver}Tooltip`)}
                  >
                    {t(`gtUsCities.driver.${driver}`)}
                  </span>
                  {city.ignition && (
                    <span
                      className="shrink-0 border border-red-300/60 bg-red-900/50 px-1 text-[10px] font-mono text-red-100"
                      title={t('gtUsCities.igniteTooltip')}
                    >
                      {t('gtUsCities.ignite')}
                    </span>
                  )}
                  <ChevronRight
                    size={GT_ICON.sm}
                    className="ml-auto shrink-0 text-white/50 group-hover:text-white"
                  />
                </div>

                <div
                  className="h-1.5 w-full overflow-hidden rounded-sm bg-slate-900/80"
                  title={t('gtUsCities.barTooltip')}
                >
                  <div
                    className="h-full bg-[linear-gradient(90deg,#dc2626,#f8fafc,#2563eb)]"
                    style={{ width: `${Math.min(100, city.protestPotential * 100)}%` }}
                  />
                </div>

                <div className={`${GT_TEXT.micro} font-mono tracking-wide text-blue-50/85`}>
                  <span title={t('gtUsCities.potentialTooltip')}>
                    potential {pct(city.protestPotential)}
                  </span>
                  <span className="text-blue-100/50"> · </span>
                  <span title={t('gtUsCities.unrestTooltip')}>
                    unrest {pct(city.unrest)}
                  </span>
                  <span className="text-blue-100/50"> · </span>
                  <span title={protestHitsTooltip}>
                    protest hits {city.protestMentions}
                  </span>
                </div>

                {city.mobilizationHits > 0 && (
                  <div
                    className="text-[10px] font-mono uppercase tracking-wider text-red-100/80"
                    title={t('gtUsCities.mobilizationTooltip')}
                  >
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

      <div className="border-t border-blue-800/30 px-2.5 py-1 text-[10px] font-mono tracking-wider text-blue-100/55">
        {t('gtUsCities.hint')}
      </div>

      <details className="group border-t border-blue-800/35 bg-blue-950/20">
        <summary
          className="cursor-pointer list-none px-2.5 py-1.5 text-[10px] font-mono font-bold uppercase tracking-widest text-blue-100/80 marker:content-none [&::-webkit-details-marker]:hidden"
          title={t('gtUsCities.personalPlanning.titleTooltip')}
        >
          <span className="inline-flex items-center gap-1.5">
            <Info size={GT_ICON.sm} className="text-blue-200/70" aria-hidden="true" />
            {t('gtUsCities.personalPlanning.title')}
            <ChevronRight
              size={GT_ICON.sm}
              className="text-blue-200/50 transition-transform group-open:rotate-90"
            />
          </span>
        </summary>
        <div className="space-y-1.5 border-t border-blue-800/25 px-2.5 py-2 text-[10px] font-mono leading-relaxed tracking-wide text-blue-100/70">
          <p title={t('gtUsCities.personalPlanning.titleTooltip')}>
            {t('gtUsCities.personalPlanning.disclaimer')}
          </p>
          <p className="text-blue-100/55">{t('gtUsCities.personalPlanning.brooklynNote')}</p>
          {nycMetro && (
            <p className="rounded-sm border border-blue-500/35 bg-blue-900/25 px-2 py-1.5 text-blue-50/90">
              {t('gtUsCities.personalPlanning.nycNow')
                .replace('{potential}', pct(nycMetro.protestPotential))
                .replace('{unrest}', pct(nycMetro.unrest))
                .replace('{hits}', String(nycMetro.protestMentions))
                .replace('{mobilization}', String(nycMetro.mobilizationHits))
                .replace(
                  '{guidance}',
                  t(
                    `gtUsCities.personalPlanning.guidance.${personalPlanningGuidanceKey(nycMetro)}`,
                  ),
                )}
            </p>
          )}
          <ul className="space-y-1 border-t border-blue-800/20 pt-1.5">
            <li>{t('gtUsCities.personalPlanning.tierRoutine')}</li>
            <li>{t('gtUsCities.personalPlanning.tierWatch')}</li>
            <li>{t('gtUsCities.personalPlanning.tierElevated')}</li>
            <li>{t('gtUsCities.personalPlanning.tierHigh')}</li>
            <li>{t('gtUsCities.personalPlanning.tierLeave')}</li>
          </ul>
        </div>
      </details>
    </div>
  );
}