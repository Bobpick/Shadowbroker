'use client';

import React, { useMemo } from 'react';
import { Cctv, GripVertical, Minus, Plus } from 'lucide-react';
import { useTranslation } from '@/i18n';
import { useFloatingPanel } from '@/hooks/useFloatingPanel';
import { useDataKey } from '@/hooks/useDataStore';
import { isFlockCamera } from '@/components/map/geoJSONBuilders';
import { GT_ICON, GT_TEXT } from '@/lib/gtTypography';
import type { CCTVCamera } from '@/types/dashboard';

interface Props {
  layerEnabled?: boolean;
  onToggle?: (enabled: boolean) => void;
  onFlyTo?: (lat: number, lng: number) => void;
}

const LIST_CAP = 40;

export default function FlockCamerasHud({
  layerEnabled = false,
  onToggle,
  onFlyTo,
}: Props) {
  const { t } = useTranslation();
  const { position, isMinimized, setIsMinimized, isDragging, onDragStart } = useFloatingPanel(
    'sb-flock-cameras-hud-v1',
    { defaultPosition: { x: 24, y: 292 } },
  );
  const cameras = useDataKey('cctv') as CCTVCamera[] | undefined;
  const cctvTotal = useDataKey('cctv_total') as number | undefined;

  const flock = useMemo(
    () => (cameras || []).filter(isFlockCamera),
    [cameras],
  );
  const inView = flock.length;
  const catalog = Number(cctvTotal || inView || 0);

  return (
    <div
      className={`pointer-events-auto fixed z-[201] flex flex-col border border-amber-700/45 bg-black/80 shadow-[0_0_16px_rgba(245,158,11,0.12)] backdrop-blur-sm ${
        isMinimized ? 'w-fit' : 'w-[min(92vw,22rem)]'
      } ${isDragging ? 'cursor-grabbing select-none' : ''}`}
      style={{ left: position.x, top: position.y }}
    >
      <div
        className={`flex items-center gap-2 bg-amber-950/30 px-2 py-1.5 cursor-grab active:cursor-grabbing ${
          isMinimized ? '' : 'border-b border-amber-800/35'
        }`}
        onMouseDown={onDragStart}
        title={t('flockHud.dragHint')}
      >
        <GripVertical size={GT_ICON.lg} className="shrink-0 text-amber-600/80" />
        <Cctv size={GT_ICON.md} className="shrink-0 text-amber-400" />
        <span className={`whitespace-nowrap ${GT_TEXT.xs} font-mono font-bold tracking-widest text-amber-300`}>
          {t('flockHud.title')}
        </span>
        <span className={`${GT_TEXT.micro} font-mono tracking-wider text-amber-500/80`}>
          {inView > 0 ? inView.toLocaleString() : catalog.toLocaleString()}
        </span>
        <button
          type="button"
          onMouseDown={(event) => event.stopPropagation()}
          onClick={() => onToggle?.(!layerEnabled)}
          className={`ml-1 px-1.5 py-0.5 font-mono tracking-widest ${GT_TEXT.micro} border ${
            layerEnabled
              ? 'border-amber-500/70 text-amber-300 bg-amber-900/40'
              : 'border-amber-800/50 text-amber-700 hover:text-amber-400'
          }`}
          title={layerEnabled ? t('flockHud.hide') : t('flockHud.show')}
        >
          {layerEnabled ? t('flockHud.on') : t('flockHud.off')}
        </button>
        <button
          type="button"
          onMouseDown={(event) => event.stopPropagation()}
          onClick={() => setIsMinimized((prev) => !prev)}
          className="ml-auto p-0.5 text-amber-500 transition-colors hover:text-amber-300"
          title={isMinimized ? t('flockHud.expand') : t('flockHud.collapse')}
        >
          {isMinimized ? <Plus size={GT_ICON.xl} /> : <Minus size={GT_ICON.xl} />}
        </button>
      </div>

      {!isMinimized && (
        <div className="flex max-h-[min(56vh,22rem)] flex-col overflow-y-auto styled-scrollbar">
          <div className={`px-2 py-1.5 ${GT_TEXT.micro} font-mono tracking-wider text-amber-600/80`}>
            {layerEnabled
              ? t('flockHud.inView').replace('{n}', String(inView)).replace('{total}', catalog.toLocaleString())
              : t('flockHud.disabled')}
          </div>
          {layerEnabled &&
            flock.slice(0, LIST_CAP).map((cam) => (
              <button
                key={String(cam.id)}
                type="button"
                onClick={() => {
                  if (cam.lat != null && cam.lon != null) onFlyTo?.(cam.lat, cam.lon);
                }}
                className="flex flex-col items-start gap-0.5 border-t border-amber-900/40 px-2 py-1.5 text-left hover:bg-amber-950/40"
              >
                <span className={`${GT_TEXT.xs} font-mono text-amber-200`}>
                  {cam.source_agency || 'Flock Safety'}
                </span>
                <span className={`${GT_TEXT.micro} font-mono text-amber-600/80`}>
                  {Number(cam.lat).toFixed(4)}, {Number(cam.lon).toFixed(4)}
                  {cam.direction_facing ? ` · ${cam.direction_facing}` : ''}
                </span>
              </button>
            ))}
          {layerEnabled && flock.length > LIST_CAP && (
            <div className={`border-t border-amber-900/40 px-2 py-1 ${GT_TEXT.micro} font-mono text-amber-700`}>
              {t('flockHud.more').replace('{n}', String(flock.length - LIST_CAP))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
