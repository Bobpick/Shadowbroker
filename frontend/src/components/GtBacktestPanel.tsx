'use client';

import React, { useCallback, useEffect, useState } from 'react';
import { CheckCircle2, Minus, Plus, Radar, RefreshCw, XCircle } from 'lucide-react';
import { API_BASE } from '@/lib/api';
import { useTranslation } from '@/i18n';
import type { GtBacktestReport } from '@/types/dashboard';

interface Props {
  layerEnabled?: boolean;
}

function pct(value: number | undefined): string {
  if (value == null || Number.isNaN(value)) return '—';
  return `${(value * 100).toFixed(1)}%`;
}

export default function GtBacktestPanel({ layerEnabled = false }: Props) {
  const { t } = useTranslation();
  const [isMinimized, setIsMinimized] = useState(false);
  const [data, setData] = useState<GtBacktestReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [showFailures, setShowFailures] = useState(false);

  const refresh = useCallback(async () => {
    if (!layerEnabled) {
      setData(null);
      return;
    }
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/analytics/backtest?expanded=true&tune=false`);
      if (res.ok) setData(await res.json());
    } catch {
      /* non-fatal */
    } finally {
      setLoading(false);
    }
  }, [layerEnabled]);

  useEffect(() => {
    refresh();
    if (!layerEnabled) return undefined;
    const id = setInterval(refresh, 15 * 60_000);
    return () => clearInterval(id);
  }, [refresh, layerEnabled]);

  const failures = (data?.cases || []).filter((row) => !row.correct);
  const passBadge = data?.meets_target;

  return (
    <div className="pointer-events-auto flex-shrink-0 border border-amber-700/40 bg-black/75 backdrop-blur-sm shadow-[0_0_18px_rgba(245,158,11,0.10)]">
      <div
        className="flex items-center justify-between border-b border-amber-700/30 bg-amber-950/20 px-3 py-2.5 cursor-pointer hover:bg-amber-950/40 transition-colors"
        onClick={() => setIsMinimized((prev) => !prev)}
      >
        <div className="flex items-center gap-2">
          <Radar size={16} className="text-amber-400" />
          <span className="text-[12px] font-mono font-bold tracking-widest text-amber-400">
            {t('gtBacktest.title').toUpperCase()}
          </span>
          {layerEnabled && data?.enabled && passBadge != null && (
            <span
              className={`text-[11px] font-mono px-1.5 py-0.5 tracking-wider border ${
                passBadge
                  ? 'bg-emerald-900/30 border-emerald-700/40 text-emerald-300'
                  : 'bg-red-900/30 border-red-700/40 text-red-300'
              }`}
            >
              {passBadge ? t('gtBacktest.pass') : t('gtBacktest.fail')}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              refresh();
            }}
            title={t('gtBacktest.refresh')}
            className="text-amber-600 transition-colors hover:text-amber-400 p-0.5"
          >
            <RefreshCw size={11} className={loading ? 'animate-spin' : ''} />
          </button>
          {isMinimized ? (
            <Plus size={16} className="text-amber-400" />
          ) : (
            <Minus size={16} className="text-amber-400" />
          )}
        </div>
      </div>

      {!isMinimized && (
        <div className="px-3 py-2 max-h-52 overflow-y-auto styled-scrollbar space-y-2">
          {!layerEnabled ? (
            <div className="text-[11px] font-mono tracking-wider text-amber-600/70 py-1">
              {t('gtBacktest.layerOff')}
            </div>
          ) : !data?.enabled ? (
            <div className="text-[11px] font-mono tracking-wider text-amber-600/70 py-1">
              {t('gtBacktest.disabled')}
            </div>
          ) : loading && !data.accuracy ? (
            <div className="text-[11px] font-mono tracking-wider text-amber-500/80 py-1">
              {t('gtBacktest.loading')}
            </div>
          ) : (
            <>
              <div className="grid grid-cols-2 gap-2">
                <div className="border border-amber-800/30 bg-amber-950/15 px-2 py-1.5">
                  <div className="text-[10px] font-mono tracking-widest text-amber-600/80">
                    {t('gtBacktest.accuracy')}
                  </div>
                  <div className="text-[13px] font-mono font-bold text-amber-200">
                    {pct(data.accuracy)}
                  </div>
                </div>
                <div className="border border-amber-800/30 bg-amber-950/15 px-2 py-1.5">
                  <div className="text-[10px] font-mono tracking-widest text-amber-600/80">
                    {t('gtBacktest.confidence')}
                  </div>
                  <div className="text-[13px] font-mono font-bold text-amber-200">
                    {pct(data.confidence_rate)}
                  </div>
                </div>
              </div>

              <div className="text-[10px] font-mono tracking-wider text-amber-600/70 leading-relaxed">
                {t('gtBacktest.cases').replace('{count}', String(data.total_cases))} ·{' '}
                {t('gtBacktest.threshold').replace('{value}', data.alert_threshold.toFixed(2))} ·{' '}
                {t('gtBacktest.target').replace('{value}', pct(data.target_confidence))}
              </div>

              <div className="flex flex-wrap gap-2 text-[10px] font-mono tracking-wider">
                <span className="text-emerald-400">TP {data.true_positives}</span>
                <span className="text-emerald-400">TN {data.true_negatives}</span>
                <span className="text-red-400">FP {data.false_positives}</span>
                <span className="text-red-400">FN {data.false_negatives}</span>
              </div>

              <div className="flex items-center gap-1.5 text-[10px] font-mono tracking-wider text-amber-500/90">
                {data.meets_target ? (
                  <CheckCircle2 size={12} className="text-emerald-400 shrink-0" />
                ) : (
                  <XCircle size={12} className="text-red-400 shrink-0" />
                )}
                <span>
                  {data.meets_target
                    ? t('gtBacktest.meetsTarget')
                    : t('gtBacktest.belowTarget')}
                </span>
              </div>

              {failures.length > 0 && (
                <div>
                  <button
                    type="button"
                    onClick={() => setShowFailures((prev) => !prev)}
                    className="text-[10px] font-mono tracking-widest text-red-400 hover:text-red-300"
                  >
                    {showFailures ? '−' : '+'} {t('gtBacktest.misclassified').replace('{count}', String(failures.length))}
                  </button>
                  {showFailures && (
                    <div className="mt-1 space-y-1">
                      {failures.map((row) => (
                        <div
                          key={row.case_id}
                          className="border border-red-800/30 bg-red-950/15 px-2 py-1 text-[10px] font-mono text-red-200/90"
                        >
                          {row.name} ({row.kind})
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );