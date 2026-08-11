import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/react';
import '@/i18n';
import StrataRail, { type RailPanel } from './strata-rail';

// jsdom implements neither Element.scrollTo nor matchMedia. Both are load-
// bearing here: scrollTo is how the folio navigates, and matchMedia is how the
// reduced-motion branch is decided.
const scrollTo = vi.fn();

function mockReducedMotion(reduce: boolean) {
  vi.stubGlobal(
    'matchMedia',
    vi.fn().mockImplementation((query: string) => ({
      matches: query.includes('prefers-reduced-motion') ? reduce : false,
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
      onchange: null,
    }))
  );
}

const PANELS: RailPanel[] = [
  {
    id: 'technicals',
    name: 'Technique',
    cadence: 'Quotidien',
    content: <div>panneau technique</div>,
  },
  { id: 'fx', name: 'FX', cadence: 'Quotidien', content: <div>panneau fx</div> },
  {
    id: 'positioning',
    name: 'Positionnement & offre',
    cadence: 'Hebdomadaire',
    content: <div>panneau positionnement</div>,
  },
];

function renderRail(panels: RailPanel[] = PANELS) {
  const view = render(<StrataRail panels={panels} />);
  const track = view.container.querySelector(
    '.strata-rail__track'
  ) as HTMLDivElement;
  return { ...view, track };
}

describe('StrataRail', () => {
  beforeEach(() => {
    scrollTo.mockClear();
    Element.prototype.scrollTo = scrollTo;
    mockReducedMotion(false);
  });

  it('renders every panel in the DOM, not just the active one', () => {
    // All strata stay mounted: find-in-page must reach a stratum the user has
    // not scrolled to yet.
    renderRail();
    expect(screen.getByText('panneau technique')).toBeInTheDocument();
    expect(screen.getByText('panneau fx')).toBeInTheDocument();
    expect(screen.getByText('panneau positionnement')).toBeInTheDocument();
  });

  it('starts on the first stratum and marks it current in the folio', () => {
    renderRail();
    const current = screen.getByRole('button', { name: 'Technique' });
    expect(current).toHaveAttribute('aria-current', 'true');
    expect(screen.getByRole('button', { name: 'FX' })).toHaveAttribute(
      'aria-current',
      'false'
    );
  });

  it('announces the settled position to screen readers', () => {
    const { container } = renderRail();
    const live = container.querySelector('.strata-rail__sr');
    expect(live).toHaveAttribute('aria-live', 'polite');
    expect(live).toHaveTextContent('Technique, 1 sur 3');
  });

  it('advances on the next chevron and updates the announcement', () => {
    const { container } = renderRail();
    fireEvent.click(screen.getByRole('button', { name: 'Strate suivante' }));

    expect(scrollTo).toHaveBeenCalledWith(
      expect.objectContaining({ behavior: 'smooth' })
    );
    expect(screen.getByRole('button', { name: 'FX' })).toHaveAttribute(
      'aria-current',
      'true'
    );
    expect(container.querySelector('.strata-rail__sr')).toHaveTextContent(
      'FX, 2 sur 3'
    );
  });

  it('navigates with the arrow keys from the track', () => {
    const { track } = renderRail();
    fireEvent.keyDown(track, { key: 'ArrowRight' });
    expect(screen.getByRole('button', { name: 'FX' })).toHaveAttribute(
      'aria-current',
      'true'
    );

    fireEvent.keyDown(track, { key: 'ArrowLeft' });
    expect(screen.getByRole('button', { name: 'Technique' })).toHaveAttribute(
      'aria-current',
      'true'
    );
  });

  it('jumps to the last stratum on End and back on Home', () => {
    const { track } = renderRail();
    fireEvent.keyDown(track, { key: 'End' });
    expect(
      screen.getByRole('button', { name: 'Positionnement & offre' })
    ).toHaveAttribute('aria-current', 'true');

    fireEvent.keyDown(track, { key: 'Home' });
    expect(screen.getByRole('button', { name: 'Technique' })).toHaveAttribute(
      'aria-current',
      'true'
    );
  });

  it('disables the chevrons at each end instead of wrapping', () => {
    renderRail();
    const prev = screen.getByRole('button', { name: 'Strate précédente' });
    const next = screen.getByRole('button', { name: 'Strate suivante' });

    expect(prev).toBeDisabled();
    expect(next).toBeEnabled();

    fireEvent.keyDown(
      document.querySelector('.strata-rail__track') as HTMLElement,
      { key: 'End' }
    );
    expect(prev).toBeEnabled();
    expect(next).toBeDisabled();
  });

  it('names the next stratum in the folio, and the end of section on the last', () => {
    const { container } = renderRail();
    const nextUp = container.querySelector(
      '.strata-rail__next-up'
    ) as HTMLElement;
    expect(nextUp).toHaveTextContent('FX · Quotidien');

    fireEvent.keyDown(
      container.querySelector('.strata-rail__track') as HTMLElement,
      { key: 'End' }
    );
    expect(nextUp).toHaveTextContent('Fin de section');
  });

  it('scrolls instantly when the user asked to reduce motion', () => {
    // The CSS `scroll-behavior` rule alone is not enough — a JS-supplied
    // `behavior: smooth` overrides it, so the branch has to live in the hook.
    // It must be 'instant': 'auto' defers back to the element's computed
    // `scroll-behavior` (smooth), which would animate anyway.
    mockReducedMotion(true);
    renderRail();
    fireEvent.click(screen.getByRole('button', { name: 'Strate suivante' }));

    expect(scrollTo).toHaveBeenCalledWith(
      expect.objectContaining({ behavior: 'instant' })
    );
    expect(scrollTo).not.toHaveBeenCalledWith(
      expect.objectContaining({ behavior: 'auto' })
    );
  });

  it('exposes each panel as a labelled slide for assistive tech', () => {
    const { container } = renderRail();
    const panels = container.querySelectorAll('.strata-rail__panel');
    expect(panels).toHaveLength(3);
    expect(panels[1]).toHaveAttribute('aria-label', '2/3 — FX');
    expect(panels[1]).toHaveAttribute('aria-roledescription', 'diapositive');
  });

  it('gives the track a single tab stop so Tab never lands off-screen', () => {
    const { track } = renderRail();
    expect(track).toHaveAttribute('tabindex', '0');
  });

  it('renders a folio entry per panel when a stratum is dropped', () => {
    // Reference is omitted when it has no data — the folio must not offer an
    // empty page.
    const { container } = renderRail(PANELS.slice(0, 2));
    const numerals = container.querySelector(
      '.strata-rail__numerals'
    ) as HTMLElement;
    expect(within(numerals).getAllByRole('button')).toHaveLength(2);
  });
});
