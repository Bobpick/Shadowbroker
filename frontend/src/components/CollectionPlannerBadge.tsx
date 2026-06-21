'use client';

import React, { useState } from 'react';
import { Satellite, Radar, ChevronDown, ChevronUp } from 'lucide-react';
import { useTranslation } from '@/i18n';
import { requestSarGuide } from '@/lib/sarGuide';
import type { CollectionPlannerBadge as PlannerBadge } from '@/lib/collectionPlanner';

export function CollectionPlannerBadge({
  badge,
  lat,
  lng,
}: {
  badge: PlannerBadge;
  lat?: number;
  lng?: number;
}) {
  const { t } = useTranslation();
  const [guideOpen, setGuideOpen] = useState(badge.sarRecommended);
  const Icon = badge.sarRecommended ? Radar : Satellite;

  return (
    <div
      className="flex flex-col gap-2 rounded border px-2.5 py-2 font-mono text-[10px] leading-snug"
      style={{
        borderColor: `${badge.color}66`,
        background: `${badge.color}14`,
        color: badge.color,
      }}
    >
      <div className="flex items-start gap-2">
        <Icon size={14} className="shrink-0 mt-0.5" />
        <div className="min-w-0">
          <div className="font-bold tracking-wider">{badge.headline}</div>
          <div className="text-[var(--text-secondary)] mt-0.5">{badge.detail}</div>
        </div>
      </div>

      {badge.sarRecommended && (
        <div className="border-t pt-2" style={{ borderColor: `${badge.color}33` }}>
          <button
            type="button"
            onClick={() => setGuideOpen((open) => !open)}
            className="flex w-full items-center justify-between gap-2 text-left text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors"
          >
            <span className="font-bold tracking-wider text-[9px]">
              {t('sarGuide.howToUse')}
            </span>
            {guideOpen ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
          </button>

          {guideOpen && (
            <div className="mt-2 space-y-1.5 text-[var(--text-secondary)] leading-relaxed">
              <p>{t('sarGuide.intro')}</p>
              <ol className="list-decimal list-inside space-y-1">
                <li>{t('sarGuide.step1')}</li>
                <li>{t('sarGuide.step2')}</li>
                <li>{t('sarGuide.step3')}</li>
                <li>{t('sarGuide.step4')}</li>
              </ol>
              <button
                type="button"
                onClick={() =>
                  requestSarGuide({
                    lat,
                    lng,
                    openAoiEditor: lat != null && lng != null,
                  })
                }
                className="mt-1 w-full rounded border px-2 py-1.5 font-bold tracking-wider transition-colors hover:brightness-125"
                style={{
                  borderColor: `${badge.color}88`,
                  background: `${badge.color}22`,
                  color: badge.color,
                }}
              >
                {t('sarGuide.enableButton')}
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}