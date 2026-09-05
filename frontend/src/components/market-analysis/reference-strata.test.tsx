import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import '@/i18n';
import ReferenceStrata from './reference-strata';
import type {
  FarmgatePriceEntry,
  FarmgatePriceResponse,
} from '@/types/dashboard';

const CIV_2026_27: FarmgatePriceEntry = {
  region: 'civ',
  campaign_type: 'principale',
  season_label: '2026/27',
  price_native: 1200,
  currency: 'XOF',
  unit: 'per_kg',
  source: 'ccc',
  source_url: null,
  effective_date: '2026-09-04',
  announced_date: '2026-09-04',
};

const PENDING_GHANA: FarmgatePriceResponse = {
  date: '2026-09-05',
  season: '2026/27',
  civ: CIV_2026_27,
  ghana: null,
};

describe('ReferenceStrata — guaranteed farmgate price', () => {
  it('publishes one card per origin for the focus season', () => {
    render(<ReferenceStrata farmgate={PENDING_GHANA} />);
    expect(screen.getByText(/1\s?200/)).toBeInTheDocument();
    expect(screen.getByText(/2026\/27 · .* · CCC/)).toBeInTheDocument();
  });

  it('says an origin is pending instead of printing last season', () => {
    // The whole point of the focus season: COCOBOD has a 2025/26 price on file,
    // and it must NOT surface under a 2026/27 dashboard.
    render(<ReferenceStrata farmgate={PENDING_GHANA} />);
    expect(screen.getByText('En attente')).toBeInTheDocument();
    expect(screen.getByText('Annonce COCOBOD à venir')).toBeInTheDocument();
    expect(screen.queryByText(/2\s?587/)).not.toBeInTheDocument();
  });

  it('renders nothing when no season has been announced at all', () => {
    const { container } = render(
      <ReferenceStrata
        farmgate={{ date: '2026-09-05', season: null, civ: null, ghana: null }}
      />
    );
    expect(container).toBeEmptyDOMElement();
  });
});
