const DEFAULT_TELEGRAM_MAX_AGE_DAYS = 7;
const MS_PER_DAY = 24 * 60 * 60 * 1000;

export function parseTelegramPublished(value?: string | null): Date | null {
  const raw = value == null ? '' : String(value).trim();
  if (!raw) return null;
  const parsed = new Date(raw);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

export function isTelegramPostWithinRetention(
  published?: string | null,
  maxAgeDays = DEFAULT_TELEGRAM_MAX_AGE_DAYS,
  nowMs = Date.now(),
): boolean {
  const date = parseTelegramPublished(published);
  if (!date) return false;
  const cutoffMs = nowMs - maxAgeDays * MS_PER_DAY;
  return date.getTime() >= cutoffMs;
}

export function filterTelegramPostsWithinRetention<T extends { published?: string | null }>(
  posts: T[],
  maxAgeDays = DEFAULT_TELEGRAM_MAX_AGE_DAYS,
  nowMs = Date.now(),
): T[] {
  return posts.filter((post) => isTelegramPostWithinRetention(post.published, maxAgeDays, nowMs));
}