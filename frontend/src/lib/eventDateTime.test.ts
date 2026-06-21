import { describe, expect, it } from 'vitest';
import { compareEventTimestampsDesc, formatEventTimestamp } from './eventDateTime';

describe('formatEventTimestamp', () => {
  it('formats ISO timestamps with date and time', () => {
    const formatted = formatEventTimestamp('2026-06-14T12:20:00Z', {
      locale: 'en-US',
      style: 'compact',
    });
    expect(formatted).toMatch(/Jun 14/);
    expect(formatted).toMatch(/·/);
  });

  it('formats RFC feed timestamps', () => {
    const formatted = formatEventTimestamp('Tue, 24 Feb 2026 15:30:00 GMT', {
      locale: 'en-US',
      style: 'compact',
    });
    expect(formatted).toContain('Feb 24');
    expect(formatted).toContain('·');
  });

  it('returns raw text when parsing fails', () => {
    expect(formatEventTimestamp('2 hours ago')).toBe('2 hours ago');
  });
});

describe('compareEventTimestampsDesc', () => {
  it('orders newest parsed timestamps first regardless of string format', () => {
    const posts = [
      { published: 'Wed, 11 Jun 2026 07:34:00 GMT' },
      { published: '2026-06-16T09:31:00Z' },
      { published: '2026-06-15T16:21:00+00:00' },
    ];
    const sorted = [...posts].sort((a, b) =>
      compareEventTimestampsDesc(a.published, b.published),
    );
    expect(sorted.map((post) => post.published)).toEqual([
      '2026-06-16T09:31:00Z',
      '2026-06-15T16:21:00+00:00',
      'Wed, 11 Jun 2026 07:34:00 GMT',
    ]);
  });

  it('sends unparsed timestamps to the bottom', () => {
    expect(compareEventTimestampsDesc('not-a-date', '2026-06-16T09:31:00Z')).toBeGreaterThan(0);
    expect(compareEventTimestampsDesc('2026-06-16T09:31:00Z', 'not-a-date')).toBeLessThan(0);
  });
});