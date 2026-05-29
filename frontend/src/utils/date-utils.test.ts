import { describe, it, expect } from 'vitest';
import { addTradingDays } from './date-utils';

// Friday 2026-05-29 is a clean weekday with no exchange holiday nearby —
// good anchor for weekend-skip tests. ISO dates throughout to mirror the
// backend's display_date → session_date contract.

describe('addTradingDays', () => {
  describe('null/invalid inputs', () => {
    it('returns null for null', () => {
      expect(addTradingDays(null, 1, new Set())).toBeNull();
    });

    it('returns null for undefined', () => {
      expect(addTradingDays(undefined, 1, new Set())).toBeNull();
    });

    it('returns null for empty string', () => {
      expect(addTradingDays('', 1, new Set())).toBeNull();
    });

    it('returns null for an unparseable ISO', () => {
      expect(addTradingDays('not-a-date', 1, new Set())).toBeNull();
    });
  });

  describe('basic weekday increment', () => {
    it('adds 1 trading day on a Monday → Tuesday', () => {
      // 2026-06-01 is a Monday
      expect(addTradingDays('2026-06-01', 1, new Set())).toBe('2026-06-02');
    });

    it('adds 4 trading days on Monday → Friday', () => {
      expect(addTradingDays('2026-06-01', 4, new Set())).toBe('2026-06-05');
    });
  });

  describe('weekend skipping', () => {
    it('skips Saturday + Sunday when starting on Friday', () => {
      // 2026-05-29 Friday → +1 trading day → 2026-06-01 Monday
      expect(addTradingDays('2026-05-29', 1, new Set())).toBe('2026-06-01');
    });

    it('crosses a weekend when adding 3 days from Wednesday', () => {
      // 2026-05-27 Wed → Thu, Fri, Mon = 2026-06-01
      expect(addTradingDays('2026-05-27', 3, new Set())).toBe('2026-06-01');
    });

    it('handles 5 trading days (full week) on Monday', () => {
      // 2026-06-01 Mon → Tue, Wed, Thu, Fri, Mon = 2026-06-08
      expect(addTradingDays('2026-06-01', 5, new Set())).toBe('2026-06-08');
    });
  });

  describe('exchange holidays skipping', () => {
    it('skips a single ISO date present in nonTradingDays', () => {
      // 2026-06-01 Mon → expects 2026-06-02 Tue normally, but Tue is a holiday
      const holidays = new Set(['2026-06-02']);
      expect(addTradingDays('2026-06-01', 1, holidays)).toBe('2026-06-03');
    });

    it('skips back-to-back holidays', () => {
      // Mon → Tue (skip) → Wed (skip) → Thu
      const holidays = new Set(['2026-06-02', '2026-06-03']);
      expect(addTradingDays('2026-06-01', 1, holidays)).toBe('2026-06-04');
    });

    it('skips a holiday that lands on a weekend (no effect — already skipped)', () => {
      // 2026-05-30 is Saturday, weekend anyway. Adding it to the set has no
      // effect because weekend skip fires first.
      const holidays = new Set(['2026-05-30']);
      expect(addTradingDays('2026-05-29', 1, holidays)).toBe('2026-06-01');
    });
  });

  describe('ISO date format edges', () => {
    it('strips an optional time component from the input', () => {
      // The function does `iso.slice(0, 10)` before parsing
      expect(addTradingDays('2026-06-01T12:30:00Z', 1, new Set())).toBe(
        '2026-06-02',
      );
    });

    it('pads single-digit months and days with zeros in the output', () => {
      // From 2026-09-30 Wed → +1 day → 2026-10-01 Thu — month change + zero pad
      const result = addTradingDays('2026-09-30', 1, new Set());
      expect(result).toBe('2026-10-01');
    });

    it('handles year boundary crossings', () => {
      // 2026-12-31 is Thursday → +1 trading day → 2027-01-01 Friday
      expect(addTradingDays('2026-12-31', 1, new Set())).toBe('2027-01-01');
    });
  });
});
