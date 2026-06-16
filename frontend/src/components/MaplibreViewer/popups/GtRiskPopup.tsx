'use client';

import React from 'react';
import { Popup } from 'react-map-gl/maplibre';
import { Radar } from 'lucide-react';
import { useTranslation } from '@/i18n';

export interface GtRiskPopupProps {
  region: string;
  risk: number;
  financial?: number;
  unrest?: number;
  conflict?: number;
  contagion?: number;
  interpretation?: string;
  lat: number;
  lng: number;
  onClose: () => void;
}

function riskColor(score: number): string {
  if (score >= 0.6) return '#ef4444';
  if (score >= 0.4) return '#f97316';
  if (score >= 0.25) return '#eab308';
  return '#22c55e';
}

export function GtRiskPopup({
  region,
  risk,
  financial,
  unrest,
  conflict,
  contagion,
  interpretation,
  lat,
  lng,
  onClose,
}: GtRiskPopupProps) {
  const { t } = useTranslation();
  const color = riskColor(risk);

  return (
    <Popup
      longitude={lng}
      latitude={lat}
      closeButton={false}
      closeOnClick={false}
      onClose={onClose}
      className="threat-popup"
      maxWidth="340px"
    >
      <div className="bg-black/95 border border-amber-700/50 rounded-lg overflow-hidden font-mono text-[11px]">
        <div className="px-3 py-2 border-b border-amber-800/40 bg-amber-950/40 flex items-center gap-2">
          <Radar size={14} className="text-amber-400" />
          <span className="text-amber-300 font-bold tracking-widest text-[10px]">
            {t('gtRisk.popupTitle')}
          </span>
          <button
            type="button"
            onClick={onClose}
            className="ml-auto text-[var(--text-muted)] hover:text-white"
          >
            ✕
          </button>
        </div>
        <div className="p-3 flex flex-col gap-2">
          <div className="flex justify-between items-center">
            <span className="text-[var(--text-muted)]">{t('gtRisk.region')}</span>
            <span className="text-white font-bold uppercase">{region}</span>
          </div>
          <div className="flex justify-between items-center">
            <span className="text-[var(--text-muted)]">{t('gtRisk.composite')}</span>
            <span className="font-bold" style={{ color }}>
              {(risk * 100).toFixed(1)}%
            </span>
          </div>
          <div className="grid grid-cols-3 gap-2 text-[10px]">
            <div>
              <div className="text-[var(--text-muted)]">{t('gtRisk.financial')}</div>
              <div className="text-cyan-300">{((financial ?? 0) * 100).toFixed(0)}%</div>
            </div>
            <div>
              <div className="text-[var(--text-muted)]">{t('gtRisk.unrest')}</div>
              <div className="text-orange-300">{((unrest ?? 0) * 100).toFixed(0)}%</div>
            </div>
            <div>
              <div className="text-[var(--text-muted)]">{t('gtRisk.conflict')}</div>
              <div className="text-red-300">{((conflict ?? 0) * 100).toFixed(0)}%</div>
            </div>
          </div>
          {contagion != null && contagion > 0 && (
            <div className="flex justify-between">
              <span className="text-[var(--text-muted)]">{t('gtRisk.contagion')}</span>
              <span className="text-purple-300">{(contagion * 100).toFixed(1)}%</span>
            </div>
          )}
          {interpretation && (
            <p className="text-[var(--text-secondary)] leading-relaxed border-t border-amber-900/40 pt-2 mt-1">
              {interpretation}
            </p>
          )}
        </div>
      </div>
    </Popup>
  );
}