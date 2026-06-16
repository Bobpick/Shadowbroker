export type EventTimestampStyle = 'compact' | 'full';

export function coerceEventDate(value?: string | number | Date | null): Date | null {
  if (value == null || value === '') return null;
  if (value instanceof Date) {
    return Number.isNaN(value.getTime()) ? null : value;
  }
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function coerceDate(value: string | number | Date): Date | null {
  return coerceEventDate(value);
}

export function eventTimestampMs(value?: string | number | Date | null): number | null {
  const date = coerceEventDate(value);
  return date ? date.getTime() : null;
}

/** Newest first; unparsed timestamps sink to the bottom. */
export function compareEventTimestampsDesc(
  left?: string | number | Date | null,
  right?: string | number | Date | null,
): number {
  const leftMs = eventTimestampMs(left);
  const rightMs = eventTimestampMs(right);
  if (leftMs == null && rightMs == null) return 0;
  if (leftMs == null) return 1;
  if (rightMs == null) return -1;
  return rightMs - leftMs;
}

function sameCalendarDay(a: Date, b: Date): boolean {
  return (
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  );
}

/**
 * Format feed/event timestamps with both date and local time.
 * Falls back to the raw string when parsing fails (RSS text dates, etc.).
 */
export function formatEventTimestamp(
  value?: string | number | Date | null,
  options?: { style?: EventTimestampStyle; locale?: string },
): string {
  const raw = value == null ? '' : String(value).trim();
  if (!raw) return '';

  const date = coerceDate(value as string | number | Date);
  if (!date) return raw;

  const locale = options?.locale;
  const style = options?.style ?? 'compact';
  const time = date.toLocaleTimeString(locale, { hour: '2-digit', minute: '2-digit' });
  const now = new Date();
  const yesterday = new Date(now);
  yesterday.setDate(yesterday.getDate() - 1);

  if (style === 'full') {
    return date.toLocaleString(locale, {
      weekday: 'short',
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  }

  if (sameCalendarDay(date, now)) {
    return `Today · ${time}`;
  }
  if (sameCalendarDay(date, yesterday)) {
    return `Yesterday · ${time}`;
  }

  const datePart = date.toLocaleDateString(locale, {
    month: 'short',
    day: 'numeric',
    ...(date.getFullYear() === now.getFullYear() ? {} : { year: 'numeric' }),
  });
  return `${datePart} · ${time}`;
}