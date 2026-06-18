'use client';

import React from 'react';
import { Satellite, Radar } from 'lucide-react';
import type { CollectionPlannerBadge as PlannerBadge } from '@/lib/collectionPlanner';

export function CollectionPlannerBadge({ badge }: { badge: PlannerBadge }) {
  const Icon = badge.sarRecommended ? Radar : Satellite;

  return (
    <div
      className="flex items-start gap-2 rounded border px-2.5 py-2 font-mono text-[10px] leading-snug"
      style={{
        borderColor: `${badge.color}66`,
        background: `${badge.color}14`,
        color: badge.color,
      }}
    >
      <Icon size={14} className="shrink-0 mt-0.5" />
      <div className="min-w-0">
        <div className="font-bold tracking-wider">{badge.headline}</div>
        <div className="text-[var(--text-secondary)] mt-0.5">{badge.detail}</div>
      </div>
    </div>
  );
}