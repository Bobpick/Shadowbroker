'use client';

import React, { useEffect, useMemo, useState } from 'react';
import { Popup } from 'react-map-gl/maplibre';
import { useTranslation } from '@/i18n';
import { REDDIT_MARKER_OFFSET } from '@/components/map/geoJSONBuilders';
import { compareEventTimestampsDesc, formatEventTimestamp } from '@/lib/eventDateTime';
import type { RedditOsintPost } from '@/types/dashboard';

export interface RedditOsintPopupProps {
  posts: RedditOsintPost[];
  lat: number;
  lng: number;
  onClose: () => void;
}

const CYRILLIC_RE = /[\u0400-\u04FF]/;
const CJK_RE = /[\u4e00-\u9fff]/;

function containsNonLatin(text: string): boolean {
  return CYRILLIC_RE.test(text) || CJK_RE.test(text);
}

function sourceLangLabel(post: RedditOsintPost): string {
  if (post.source_lang_label) return post.source_lang_label;
  const code = String(post.source_lang || '').trim().toLowerCase();
  const labels: Record<string, string> = {
    uk: 'Ukrainian',
    ru: 'Russian',
    en: 'English',
    ar: 'Arabic',
    he: 'Hebrew',
    'zh-cn': 'Chinese',
    fr: 'French',
    de: 'German',
    pl: 'Polish',
  };
  return labels[code] || code.toUpperCase();
}

function hasTranslation(post: RedditOsintPost): boolean {
  const translated = String(post.title_translated || post.description_translated || '').trim();
  const original = String(post.title || post.description || '').trim();
  return Boolean(translated && translated !== original);
}

function postHeadline(post: RedditOsintPost, showOriginal: boolean): string {
  const original = String(post.title || post.description || 'Reddit post').trim();
  const translated = String(post.title_translated || post.description_translated || '').trim();
  if (!showOriginal && translated) {
    return translated.split('\n', 1)[0].trim();
  }
  if (!showOriginal && containsNonLatin(original) && translated) {
    return translated.split('\n', 1)[0].trim();
  }
  return original;
}

function postDetail(post: RedditOsintPost, showOriginal: boolean): string | null {
  if (!showOriginal && post.description_translated) {
    const translatedTitle = String(post.title_translated || '').trim();
    const translatedBody = String(post.description_translated || '').trim();
    if (!translatedBody || translatedBody === translatedTitle) return null;
    const extra = translatedBody.startsWith(translatedTitle)
      ? translatedBody.slice(translatedTitle.length).trim()
      : translatedBody;
    return extra || null;
  }

  const title = String(post.title || '').trim();
  const description = String(post.description || '').trim();
  if (!description || description === title || description.startsWith(title)) return null;
  const extra = description.startsWith(title) ? description.slice(title.length).trim() : description;
  return extra || null;
}

function profileLabel(profile?: string): string {
  if (profile === 'protest') return 'PROTEST';
  if (profile === 'adversarial') return 'ADVERSARIAL NARRATIVE';
  if (profile === 'geopolitical') return 'GEOPOLITICAL';
  return 'GENERAL';
}

function profileClass(profile?: string): string {
  if (profile === 'protest') return 'text-rose-200 border-rose-500/40 bg-rose-950/25';
  if (profile === 'adversarial') return 'text-orange-300 border-orange-500/40 bg-orange-950/30';
  if (profile === 'geopolitical') return 'text-amber-200 border-amber-500/30 bg-amber-950/20';
  return 'text-gray-300 border-gray-600/30 bg-gray-900/30';
}

function RedditPostCard({ post, locale }: { post: RedditOsintPost; locale: string }) {
  const { t } = useTranslation();
  const [showOriginal, setShowOriginal] = useState(false);
  const translated = hasTranslation(post);
  const headline = postHeadline(post, showOriginal);
  const detail = postDetail(post, showOriginal);

  return (
    <div className={`rounded border px-2 py-1.5 ${profileClass(post.narrative_profile)}`}>
      <div className="flex items-start justify-between gap-2">
        <a
          href={post.link}
          target="_blank"
          rel="noopener noreferrer"
          className="text-[11px] font-bold text-orange-100 hover:text-white"
        >
          {headline}
        </a>
        <span className="shrink-0 text-[9px] tracking-wider text-orange-400/90">
          {profileLabel(post.narrative_profile)}
        </span>
      </div>
      <div className="mt-1 text-[10px] text-orange-400/85">
        {post.source || 'reddit'}
        {post.published ? ` · ${formatEventTimestamp(post.published, { locale, style: 'compact' })}` : ''}
        {typeof post.reddit_score === 'number' ? ` · score ${post.reddit_score}` : ''}
      </div>
      {detail ? (
        <div className="mt-1 line-clamp-4 text-[10px] text-orange-100/85 whitespace-pre-wrap">{detail}</div>
      ) : null}
      {translated && !showOriginal && post.source_lang ? (
        <p className="mt-1 text-[9px] text-orange-600/80 uppercase tracking-wider">
          {t('reddit.translatedFrom').replace('{lang}', sourceLangLabel(post))}
        </p>
      ) : null}
      {translated ? (
        <div className="mt-1 flex items-center gap-2">
          <button
            type="button"
            onClick={() => setShowOriginal((prev) => !prev)}
            className="text-[9px] font-mono text-orange-500 hover:text-orange-200 transition-colors"
          >
            {showOriginal
              ? t('reddit.showTranslation')
              : t('reddit.showOriginal').replace('{lang}', sourceLangLabel(post))}
          </button>
        </div>
      ) : null}
    </div>
  );
}

export function RedditOsintPopup({ posts, lat, lng, onClose }: RedditOsintPopupProps) {
  const { locale, t } = useTranslation();
  const [localizedPosts, setLocalizedPosts] = useState(posts);

  useEffect(() => {
    setLocalizedPosts(posts);
  }, [posts]);

  useEffect(() => {
    const needsLocalizedFeed = posts.some((post) => !hasTranslation(post));
    if (!needsLocalizedFeed) {
      return;
    }

    let cancelled = false;
    const controller = new AbortController();

    fetch(`/api/reddit-feed?lang=${encodeURIComponent(locale)}`, { signal: controller.signal })
      .then((response) => (response.ok ? response.json() : null))
      .then((payload) => {
        if (cancelled || !payload?.posts) return;
        const byId = new Map(
          (payload.posts as RedditOsintPost[]).map((post) => [post.id, post]),
        );
        setLocalizedPosts(posts.map((post) => byId.get(post.id) || post));
      })
      .catch(() => {
        /* keep map posts when locale translation fetch fails */
      });

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [locale, posts]);

  const ordered = useMemo(
    () => [...localizedPosts].sort((a, b) => compareEventTimestampsDesc(a.published, b.published)),
    [localizedPosts],
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

        <div className="mb-2 border border-amber-700/40 bg-black/60 p-2 text-[11px] leading-relaxed text-amber-100/90 relative overflow-hidden">
          <div className="absolute top-0 left-0 h-full w-[2px] bg-amber-500/80" />
          <span className="font-bold text-amber-300">&gt;_ SYS.NOTICE: </span>
          {t('reddit.disclaimer')}
        </div>

        <div className="flex max-h-[min(50vh,320px)] flex-col gap-2 overflow-y-auto styled-scrollbar">
          {ordered.map((post) => (
            <RedditPostCard key={post.id} post={post} locale={locale} />
          ))}
        </div>
      </div>
    </Popup>
  );
}