import { describe, expect, it } from 'vitest';
import {
  filterTelegramPostsWithinRetention,
  isTelegramPostWithinRetention,
} from './telegramRetention';

const NOW = Date.parse('2026-06-16T12:00:00Z');

describe('telegramRetention', () => {
  it('keeps posts within the retention window using full ISO year', () => {
    expect(
      isTelegramPostWithinRetention('2026-06-15T12:00:00Z', 7, NOW),
    ).toBe(true);
    expect(
      isTelegramPostWithinRetention('2022-06-17T15:30:00Z', 7, NOW),
    ).toBe(false);
  });

  it('drops posts with missing or invalid published timestamps', () => {
    expect(isTelegramPostWithinRetention(undefined, 7, NOW)).toBe(false);
    expect(isTelegramPostWithinRetention('not-a-date', 7, NOW)).toBe(false);
  });

  it('filters post lists before map rendering', () => {
    const kept = filterTelegramPostsWithinRetention(
      [
        { id: 'fresh', published: '2026-06-15T12:00:00Z' },
        { id: 'stale', published: '2022-06-17T15:30:00Z' },
      ],
      7,
      NOW,
    );
    expect(kept.map((post) => post.id)).toEqual(['fresh']);
  });
});