import { Info } from 'lucide-react';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';

/**
 * Inline explanation mark for a block header.
 *
 * Used where the *method* is the thing a reader can get wrong — season-to-date
 * being compared against the equivalent period rather than the full previous
 * season, and each source carrying its own window. That is not a caption's job:
 * it is three sentences, and printing them under every block would bury the
 * numbers. `focusable` so it is reachable without a pointer.
 */
export default function HelpTip({ title, body }: { title: string; body: string }) {
  return (
    <TooltipProvider delayDuration={150}>
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            type="button"
            aria-label={title}
            className="inline-flex items-center justify-center cursor-help"
            style={{ color: 'var(--ink-light)', padding: 2, marginLeft: 2 }}
          >
            <Info size={12} strokeWidth={2.2} />
          </button>
        </TooltipTrigger>
        <TooltipContent
          side="top"
          sideOffset={8}
          className="max-w-[330px] p-0 border-0 rounded-none shadow-[0_8px_20px_rgba(0,0,0,0.25)]"
          style={{ background: 'var(--ink)', color: 'var(--paper)' }}
        >
          <div style={{ padding: '11px 13px' }}>
            <div
              className="uppercase"
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 9,
                fontWeight: 600,
                letterSpacing: '0.18em',
                opacity: 0.72,
                marginBottom: 6,
              }}
            >
              {title}
            </div>
            <p
              style={{
                fontFamily: 'var(--font-editorial)',
                fontSize: 12.5,
                lineHeight: 1.55,
                margin: 0,
              }}
            >
              {body}
            </p>
          </div>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
