'use client';

import React from 'react';
import { GripVertical, Minus, Plus } from 'lucide-react';
import { useTranslation } from '@/i18n';
import { useFloatingPanel } from '@/hooks/useFloatingPanel';
import GtBacktestPanel from '@/components/GtBacktestPanel';
import GtTopAlertsStrip from '@/components/GtTopAlertsStrip';
import GtUsCitiesPanel from '@/components/GtUsCitiesPanel';
import StrategicAnalysisPanel from '@/components/StrategicAnalysisPanel';
import { GT_ICON, GT_TEXT } from '@/lib/gtTypography';
import type { SelectedEntity } from '@/types/dashboard';

interface Props {
  layerEnabled?: boolean;
  onFlyTo?: (lat: number, lng: number) => void;
  onSelectEntity?: (entity: SelectedEntity | null) => void;
}

export default function GtAnalyticsHud({
  layerEnabled = false,
  onFlyTo,
  onSelectEntity,
}: Props) {
  const { t } = useTranslation();
  const { position, isMinimized, setIsMinimized, isDragging, onDragStart } = useFloatingPanel(
    'sb-gt-analytics-hud-v1',
    { defaultPosition: { x: 24, y: 380 } },
  );

  if (!layerEnabled) return null;

  return (
    <div
      className={`pointer-events-auto fixed z-[201] flex flex-col border border-amber-700/45 bg-black/80 shadow-[0_0_16px_rgba(245,158,11,0.12)] backdrop-blur-sm ${
        isMinimized ? 'w-fit' : 'w-[min(92vw,34rem)]'
      } ${isDragging ? 'cursor-grabbing select-none' : ''}`}
      style={{ left: position.x, top: position.y }}
    >
      <div
        className={`flex items-center gap-2 bg-amber-950/30 px-2 py-1.5 cursor-grab active:cursor-grabbing ${
          isMinimized ? '' : 'border-b border-amber-800/35'
        }`}
        onMouseDown={onDragStart}
        title={t('gtHud.dragHint')}
      >
        <GripVertical size={GT_ICON.lg} className="shrink-0 text-amber-600/80" />
        <span className={`whitespace-nowrap ${GT_TEXT.xs} font-mono font-bold tracking-widest text-amber-300`}>
          {t('gtHud.title')}
        </span>
        {!isMinimized && (
          <span className={`${GT_TEXT.micro} font-mono tracking-wider text-amber-600/70`}>
            {t('gtHud.dragHint')}
          </span>
        )}
        <button
          type="button"
          onMouseDown={(event) => event.stopPropagation()}
          onClick={() => setIsMinimized((prev) => !prev)}
          className="ml-auto p-0.5 text-amber-500 transition-colors hover:text-amber-300"
          title={isMinimized ? t('gtHud.expand') : t('gtHud.collapse')}
        >
          {isMinimized ? <Plus size={GT_ICON.xl} /> : <Minus size={GT_ICON.xl} />}
        </button>
      </div>

      {!isMinimized && (
        <div className="flex max-h-[min(72vh,36rem)] flex-col overflow-y-auto styled-scrollbar">
          <GtUsCitiesPanel
            layerEnabled={layerEnabled}
            onFlyTo={onFlyTo}
            onSelectEntity={onSelectEntity}
            embedded
          />
          <StrategicAnalysisPanel
            layerEnabled={layerEnabled}
            onFlyTo={onFlyTo}
            embedded
          />
          <GtBacktestPanel layerEnabled={layerEnabled} embedded />
          <GtTopAlertsStrip
            layerEnabled={layerEnabled}
            onFlyTo={onFlyTo}
            onSelectEntity={onSelectEntity}
            embedded
          />
        </div>
      )}
    </div>
  );
}