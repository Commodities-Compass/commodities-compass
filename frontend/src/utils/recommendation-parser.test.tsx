import { describe, it, expect } from 'vitest';
import { parseConclusion } from './recommendation-parser';

// Pure tests for `parseConclusion` — splits raw recommendation lines into
// `analysis` (default bucket) and `watchlist` (after the "À surveiller"
// sentinel). The `>` lead character on editorial paragraphs is stripped.

describe('parseConclusion', () => {
  it('returns empty buckets for empty input', () => {
    expect(parseConclusion([])).toEqual({ analysis: [], watchlist: [] });
  });

  it('puts everything in analysis when no watchlist sentinel', () => {
    const items = ['Line A', 'Line B', '> Line C'];
    expect(parseConclusion(items)).toEqual({
      analysis: ['Line A', 'Line B', 'Line C'],
      watchlist: [],
    });
  });

  it('switches to watchlist after the sentinel (case-insensitive, ASCII only)', () => {
    // The regex /a surveiller/i is ASCII case-insensitive — the accented
    // "À" does NOT match (Unicode diacritic folding is not enabled).
    const items = [
      '> Open recommandation',
      '> Holding signal',
      'A SURVEILLER AUJOURDHUI:',
      '> Daily close > 2600',
      '> RSI break of 70',
    ];
    expect(parseConclusion(items)).toEqual({
      analysis: ['Open recommandation', 'Holding signal'],
      watchlist: ['Daily close > 2600', 'RSI break of 70'],
    });
  });

  it('strips a leading > and surrounding whitespace', () => {
    const items = ['  >   Hello ', '>World'];
    expect(parseConclusion(items)).toEqual({
      analysis: ['Hello', 'World'],
      watchlist: [],
    });
  });

  it('skips blank lines on either side of the sentinel', () => {
    const items = ['Line A', '', '   ', 'a surveiller', '', '> Tail item'];
    expect(parseConclusion(items)).toEqual({
      analysis: ['Line A'],
      watchlist: ['Tail item'],
    });
  });

  it('discards lines that become empty after stripping the > prefix', () => {
    const items = ['>', '>   ', 'A surveiller', '>'];
    expect(parseConclusion(items)).toEqual({
      analysis: [],
      watchlist: [],
    });
  });

  it('matches the sentinel with arbitrary trailing text', () => {
    // Regex uses /a surveiller/i (no accents). LLM prompts produce the
    // unaccented variant in the bullet that drives this split.
    const items = [
      'Main thesis',
      'A SURVEILLER AUJOURDHUI : niveau cle 2600',
      '> Level break',
    ];
    expect(parseConclusion(items)).toEqual({
      analysis: ['Main thesis'],
      watchlist: ['Level break'],
    });
  });
});
