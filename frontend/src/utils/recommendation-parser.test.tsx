import { describe, it, expect } from 'vitest';
import { parseConclusion } from './recommendation-parser';

// `parseConclusion` splits the recommendation lines (as produced by the backend
// `parse_recommendations_text`: bullets stripped, only the two section headers
// keep their leading ">") into `analysis` (before the watch header) and
// `watchlist` (after it). The split is STRUCTURAL — the first ">" line is the
// headline, the second marks the watch section — so it is language-agnostic
// (FR "A SURVEILLER", EN "TO WATCH", …), which is what unblocks EN content.

describe('parseConclusion', () => {
  it('returns empty buckets for empty input', () => {
    expect(parseConclusion([])).toEqual({ analysis: [], watchlist: [] });
  });

  it('puts everything in analysis when there is no watch section', () => {
    const items = ['> Lecture défensive', 'Le CLOSE recule', 'Le RSI est neutre'];
    expect(parseConclusion(items)).toEqual({
      analysis: ['Lecture défensive', 'Le CLOSE recule', 'Le RSI est neutre'],
      watchlist: [],
    });
  });

  it('splits FR: analysis before, watchlist after the "A SURVEILLER" header', () => {
    const items = [
      '> Lecture Compass alignée sur MONITOR',
      "Le CLOSE s'établit à 3746",
      'Le RSI est à 60.9521',
      "> A SURVEILLER AUJOURD'HUI:",
      'Baissier si le CLOSE passe sous le SUPPORT 1',
      'Baissier si le RSI repasse sous 58',
    ];
    expect(parseConclusion(items)).toEqual({
      analysis: [
        'Lecture Compass alignée sur MONITOR',
        "Le CLOSE s'établit à 3746",
        'Le RSI est à 60.9521',
      ],
      watchlist: [
        'Baissier si le CLOSE passe sous le SUPPORT 1',
        'Baissier si le RSI repasse sous 58',
      ],
    });
  });

  it('splits EN identically — the header word is not hard-coded', () => {
    const items = [
      '> Compass reading aligned with MONITOR',
      'CLOSE settles at 3746',
      '> TO WATCH TODAY:',
      'Bearish if CLOSE breaks below SUPPORT 1',
    ];
    expect(parseConclusion(items)).toEqual({
      analysis: ['Compass reading aligned with MONITOR', 'CLOSE settles at 3746'],
      watchlist: ['Bearish if CLOSE breaks below SUPPORT 1'],
    });
  });

  it('strips the leading > from the headline', () => {
    expect(parseConclusion(['  >   Lecture du jour '])).toEqual({
      analysis: ['Lecture du jour'],
      watchlist: [],
    });
  });

  it('skips blank lines around the watch header', () => {
    const items = ['> Head', '', '   ', 'Body', '> A SURVEILLER:', '', 'Alert'];
    expect(parseConclusion(items)).toEqual({
      analysis: ['Head', 'Body'],
      watchlist: ['Alert'],
    });
  });

  it('discards header lines that are empty after stripping >', () => {
    const items = ['>', 'Body', '> A SURVEILLER:', '>   '];
    expect(parseConclusion(items)).toEqual({
      analysis: ['Body'],
      watchlist: [],
    });
  });
});
