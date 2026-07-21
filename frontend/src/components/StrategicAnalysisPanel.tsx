'use client';

/**
 * Nash Equilibrium / Deterrence dashboard — embedded in GtAnalyticsHud.
 * Payoff matrices, Nash stability, deterrence meters, delta report controls.
 */

import React, { useCallback, useEffect, useState } from 'react';
import { Crosshair, FileText, RefreshCw, Shield, Target } from 'lucide-react';
import { useTranslation } from '@/i18n';
import { GT_ICON, GT_TEXT } from '@/lib/gtTypography';
import {
  detBandClass,
  fetchDeltaReportStatus,
  fetchStrategicAnalysis,
  generateDeltaReport,
  nashBandClass,
  type DeltaReportResult,
  type StrategicFlashpoint,
  type StrategicAnalysisPayload,
} from '@/lib/strategicAnalysis';

interface Props {
  layerEnabled?: boolean;
  embedded?: boolean;
  onFlyTo?: (lat: number, lng: number) => void;
}

function PayoffMatrix({ fp }: { fp: StrategicFlashpoint }) {
  const payoffs = fp.payoffs || [];
  const rowS = fp.row_strategies || ['C', 'D'];
  const colS = fp.col_strategies || ['C', 'D'];
  const eqs = new Set((fp.equilibria || []).map(([r, c]) => `${r},${c}`));
  const cur = `${fp.current_row ?? 0},${fp.current_col ?? 0}`;

  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-[10px] font-mono">
        <thead>
          <tr>
            <th className="p-1 text-left text-amber-600/70">
              {fp.row_actor || 'Row'} \\ {fp.col_actor || 'Col'}
            </th>
            {colS.map((c) => (
              <th key={c} className="p-1 text-amber-500/80 font-normal">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {payoffs.map((row, ri) => (
            <tr key={ri}>
              <td className="p-1 text-amber-500/80">{rowS[ri] ?? ri}</td>
              {row.map((cell, ci) => {
                const key = `${ri},${ci}`;
                const isEq = eqs.has(key);
                const isCur = key === cur;
                return (
                  <td
                    key={ci}
                    className={`border p-1 text-center ${
                      isEq
                        ? 'border-emerald-500/60 bg-emerald-950/40 text-emerald-100'
                        : 'border-amber-800/35 text-amber-100/85'
                    } ${isCur ? 'ring-1 ring-amber-300/70' : ''}`}
                    title={
                      isEq
                        ? 'Pure Nash equilibrium'
                        : isCur
                          ? 'Current inferred play'
                          : 'Payoff (row, col)'
                    }
                  >
                    {Array.isArray(cell)
                      ? `${Number(cell[0]).toFixed(1)}, ${Number(cell[1]).toFixed(1)}`
                      : '—'}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <div className="mt-1 text-[9px] font-mono text-amber-600/65">
        ring = current · green cell = pure Nash · arrow:{' '}
        {fp.arrow?.label || '—'}
        {fp.arrow && fp.arrow.label === 'toward_eq'
          ? ` (${fp.arrow.from?.[0]},${fp.arrow.from?.[1]} → ${fp.arrow.to?.[0]},${fp.arrow.to?.[1]})`
          : ''}
      </div>
    </div>
  );
}

export default function StrategicAnalysisPanel({
  layerEnabled = false,
  embedded = false,
  onFlyTo,
}: Props) {
  const { t } = useTranslation();
  const [data, setData] = useState<StrategicAnalysisPayload | null>(null);
  const [loading, setLoading] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [deltaStatus, setDeltaStatus] = useState<DeltaReportResult | null>(null);
  const [deltaBusy, setDeltaBusy] = useState(false);
  const [previewMd, setPreviewMd] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!layerEnabled) return;
    setLoading(true);
    setError(null);
    try {
      const [strategic, delta] = await Promise.all([
        fetchStrategicAnalysis(),
        fetchDeltaReportStatus(),
      ]);
      setData(strategic);
      setDeltaStatus(delta);
      if (strategic.flashpoints?.length && !selectedId) {
        setSelectedId(strategic.flashpoints[0].id);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'load failed');
    } finally {
      setLoading(false);
    }
  }, [layerEnabled, selectedId]);

  useEffect(() => {
    void refresh();
    if (!layerEnabled) return;
    const tid = setInterval(() => void refresh(), 60_000);
    return () => clearInterval(tid);
  }, [layerEnabled, refresh]);

  const runDelta = async (mode: 'preview' | 'force') => {
    setDeltaBusy(true);
    setError(null);
    try {
      const result = await generateDeltaReport({
        preview: mode === 'preview',
        force: mode === 'force',
      });
      if (result.markdown) setPreviewMd(result.markdown);
      if (result.reason && result.skipped) {
        setError(String(result.reason));
      }
      const status = await fetchDeltaReportStatus();
      setDeltaStatus(status);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'report failed');
    } finally {
      setDeltaBusy(false);
    }
  };

  if (!layerEnabled) return null;

  const shellClass = embedded
    ? 'pointer-events-auto flex-shrink-0 border-b border-amber-800/30 bg-black/70'
    : 'pointer-events-auto max-w-[min(92vw,34rem)] border border-amber-700/45 bg-black/80 backdrop-blur-sm shadow-[0_0_16px_rgba(245,158,11,0.12)]';

  const selected =
    data?.flashpoints?.find((f) => f.id === selectedId) || data?.flashpoints?.[0] || null;

  return (
    <div className={shellClass}>
      <div className="flex items-center gap-2 border-b border-amber-800/35 bg-amber-950/25 px-2.5 py-1.5">
        <Shield size={GT_ICON.lg} className="shrink-0 text-amber-400" />
        <span className={`${GT_TEXT.xs} font-mono font-bold tracking-widest text-amber-300`}>
          {t('strategicAnalysis.title')}
        </span>
        {data?.enabled && (
          <span className={`${GT_TEXT.micro} font-mono tracking-wider text-amber-600/80`}>
            {t('strategicAnalysis.counts')
              .replace('{n}', String(data.flashpoint_count ?? data.flashpoints?.length ?? 0))
              .replace('{fragile}', String(data.fragile_count ?? 0))
              .replace('{unstable}', String(data.unstable_count ?? 0))}
          </span>
        )}
        <button
          type="button"
          onClick={() => void refresh()}
          className="ml-auto p-0.5 text-amber-600 hover:text-amber-300"
          title={t('strategicAnalysis.refresh')}
        >
          <RefreshCw size={GT_ICON.sm} className={loading ? 'animate-spin' : ''} />
        </button>
      </div>

      <div className="max-h-[22rem] space-y-2 overflow-y-auto styled-scrollbar px-2.5 py-2">
        {!data?.enabled ? (
          <div className={`${GT_TEXT.micro} font-mono text-amber-600/70`}>
            {data?.message || t('strategicAnalysis.disabled')}
          </div>
        ) : (
          <>
            <div className="flex flex-wrap gap-1">
              {(data.flashpoints || []).map((fp) => (
                <button
                  key={fp.id}
                  type="button"
                  onClick={() => {
                    setSelectedId(fp.id);
                    if (fp.lat != null && fp.lng != null) onFlyTo?.(fp.lat, fp.lng);
                  }}
                  className={`border px-1.5 py-0.5 font-mono text-[10px] tracking-wider transition-colors ${
                    selected?.id === fp.id
                      ? 'border-amber-500/60 bg-amber-900/35 text-amber-100'
                      : 'border-amber-800/35 text-amber-600/80 hover:text-amber-300'
                  }`}
                >
                  {fp.label}
                </button>
              ))}
            </div>

            {selected && (
              <div className={`border p-2 ${nashBandClass(selected.nash_band)}`}>
                <div className="mb-1.5 flex flex-wrap items-center gap-2">
                  <Target size={GT_ICON.sm} className="shrink-0" />
                  <span className={`${GT_TEXT.xs} font-mono font-bold uppercase tracking-widest`}>
                    {selected.label}
                  </span>
                  <span className="border border-current/40 px-1 text-[9px] font-mono uppercase">
                    Nash {selected.nash_score?.toFixed?.(0) ?? selected.nash_score}/100 ·{' '}
                    {selected.nash_band}
                  </span>
                </div>

                <div className="mb-2">
                  <div className="mb-0.5 flex items-center justify-between text-[9px] font-mono uppercase tracking-wider opacity-80">
                    <span>{t('strategicAnalysis.deterrence')}</span>
                    <span>
                      {selected.deterrence?.score?.toFixed?.(0)} · {selected.deterrence?.band}
                    </span>
                  </div>
                  <div className="h-1.5 w-full overflow-hidden rounded-sm bg-black/40">
                    <div
                      className={`h-full ${detBandClass(selected.deterrence?.band)}`}
                      style={{
                        width: `${Math.min(100, Math.max(0, selected.deterrence?.score ?? 0))}%`,
                      }}
                    />
                  </div>
                  <div className="mt-0.5 text-[9px] font-mono opacity-70">
                    GT max {(selected.deterrence?.max_gt_risk ?? 0) * 100}% · feed hits{' '}
                    {selected.keyword_hits ?? 0}
                  </div>
                </div>

                <PayoffMatrix fp={selected} />
              </div>
            )}

            {/* Delta report controls */}
            <div className="border border-amber-800/30 bg-amber-950/15 p-2">
              <div className="mb-1 flex items-center gap-1.5">
                <FileText size={GT_ICON.sm} className="text-amber-400" />
                <span className={`${GT_TEXT.micro} font-mono font-bold tracking-widest text-amber-300`}>
                  {t('strategicAnalysis.deltaTitle')}
                </span>
              </div>
              <div className="mb-1.5 text-[9px] font-mono text-amber-600/70">
                {deltaStatus?.last?.timestamp
                  ? t('strategicAnalysis.deltaLast').replace(
                      '{ts}',
                      String(deltaStatus.last.timestamp),
                    )
                  : t('strategicAnalysis.deltaNever')}
              </div>
              <div className="flex flex-wrap gap-1">
                <button
                  type="button"
                  disabled={deltaBusy}
                  onClick={() => void runDelta('preview')}
                  className="border border-amber-700/45 bg-amber-950/25 px-2 py-0.5 text-[10px] font-mono tracking-widest text-amber-300 hover:bg-amber-900/35 disabled:opacity-50"
                >
                  {t('strategicAnalysis.preview')}
                </button>
                <button
                  type="button"
                  disabled={deltaBusy}
                  onClick={() => void runDelta('force')}
                  className="border border-amber-500/50 bg-amber-900/30 px-2 py-0.5 text-[10px] font-mono tracking-widest text-amber-100 hover:bg-amber-800/40 disabled:opacity-50"
                >
                  {t('strategicAnalysis.generateNow')}
                </button>
              </div>
              {previewMd && (
                <pre className="mt-2 max-h-40 overflow-auto whitespace-pre-wrap border border-amber-800/25 bg-black/40 p-1.5 text-[9px] font-mono leading-relaxed text-amber-100/80">
                  {previewMd.slice(0, 4000)}
                  {previewMd.length > 4000 ? '\n…' : ''}
                </pre>
              )}
            </div>

            {error && (
              <div className="text-[10px] font-mono text-red-300/90">{error}</div>
            )}

            <div className="flex items-start gap-1 text-[9px] font-mono text-amber-600/55">
              <Crosshair size={10} className="mt-0.5 shrink-0" />
              <span>{t('strategicAnalysis.hint')}</span>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
