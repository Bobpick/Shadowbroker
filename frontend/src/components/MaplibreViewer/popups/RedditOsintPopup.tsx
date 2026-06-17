'use client';

import React, { useMemo } from 'react';
import { Popup } from 'react-map-gl/maplibre';
import { REDDIT_MARKER_OFFSET } from '@/components/map/geoJSONBuilders';
import { compareEventTimestampsDesc, formatEventTimestamp } from '@/lib/eventDateTime';
import type { RedditOsintPost } from '@/types/dashboard';

export interface RedditOsintPopupProps {
  posts: RedditOsintPost[];
  lat: number;
  lng: number;
  onClose: () => void;
}

function profileLabel(profile?: string): string {
  if (profile === 'adversarial') return 'ADVERSARIAL NARRATIVE';
  if (profile === 'geopolitical') return 'GEOPOLITICAL';
  return 'GENERAL';
}

function profileClass(profile?: string): string {
  if (profile === 'adversarial') return 'text-orange-300 border-orange-500/40 bg-orange-950/30';
  if (profile === 'geopolitical') return 'text-amber-200 border-amber-500/30 bg-amber-950/20';
  return 'text-gray-300 border-gray-600/30 bg-gray-900/30';
}

export function RedditOsintPopup({ posts, lat, lng, onClose }: RedditOsintPopupProps) {
  const ordered = useMemo(
    () => [...posts].sort((a, b) => compareEventTimestampsDesc(a.published, b.published)),
    [posts],
  );

  return (
    <Popup
      longitude={lng}
      latitude={lat}
      closeButton={false}
      closeOnClick={false}
      onClose={onClose}
      anchor="bottom"
      offset={REDDIT_MARKER_OFFSET}
      maxWidth="360px"
      className="threat-popup"
    >
      <div className="map-popup min-w-[280px] border border-orange-500/40 bg-[#120a06]/95 font-mono text-orange-50">
        <div className="mb-2 flex items-start justify-between gap-3 border-b border-orange-500/20 pb-2">
          <div>
            <div className="text-[11px] font-bold tracking-[0.25em] text-orange-300">
              REDDIT OSINT
            </div>
            <div className="mt-1 text-[10px] text-orange-500/80">
              Public narrative monitor · {ordered.length} post{ordered.length === 1 ? '' : 's'}
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-orange-600 transition-colors hover:text-orange-200"
            aria-label="Close Reddit OSINT summary"
          >
            ✕
          </button>
        </div>

        <div className="flex max-h-[min(50vh,320px)] flex-col gap-2 overflow-y-auto styled-scrollbar">
          {ordered.map((post) => (
            <div
              key={post.id}
              className={`rounded border px-2 py-1.5 ${profileClass(post.narrative_profile)}`}
            >
              <div className="flex items-start justify-between gap-2">
                <a
                  href={post.link}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-[11px] font-bold text-orange-100 hover:text-white"
                >
                  {post.title || 'Reddit post'}
                </a>
                <span className="shrink-0 text-[9px] tracking-wider text-orange-400/90">
                  {profileLabel(post.narrative_profile)}
                </span>
              </div>
              <div className="mt-1 text-[10px] text-orange-400/85">
                {post.source || 'reddit'}
                {post.published ? ` · ${formatEventTimestamp(post.published)}` : ''}
                {typeof post.reddit_score === 'number' ? ` · score ${post.reddit_score}` : ''}
              </div>
              {post.description ? (
                <div className="mt-1 line-clamp-4 text-[10px] text-orange-100/85">
                  {post.description}
                </div>
              ) : null}
            </div>
          ))}
        </div>
      </div>
    </Popup>
  );
}