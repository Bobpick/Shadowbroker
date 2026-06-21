const DEFAULT_REDDIT_MAX_AGE_DAYS = 7;
const MS_PER_DAY = 24 * 60 * 60 * 1000;

export function parseRedditPublished(value?: string | null): Date | null {
  const raw = value == null ? '' : String(value).trim();
  if (!raw) return null;
  const parsed = new Date(raw);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

export function isRedditPostWithinRetention(
  published?: string | null,
  maxAgeDays = DEFAULT_REDDIT_MAX_AGE_DAYS,
  nowMs = Date.now(),
): boolean {
  const date = parseRedditPublished(published);
  if (!date) return false;
  const cutoffMs = nowMs - maxAgeDays * MS_PER_DAY;
  return date.getTime() >= cutoffMs;
}

export function filterRedditPostsWithinRetention<T extends { published?: string | null }>(
  posts: T[],
  maxAgeDays = DEFAULT_REDDIT_MAX_AGE_DAYS,
  nowMs = Date.now(),
): T[] {
  return posts.filter((post) => isRedditPostWithinRetention(post.published, maxAgeDays, nowMs));
}