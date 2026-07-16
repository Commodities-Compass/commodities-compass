import { useEffect, useRef } from 'react';
import { LogOutIcon, MenuIcon, UserIcon } from 'lucide-react';
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar';
import { useAuth } from '@/hooks/useAuth';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { useDashboardDate } from '@/hooks/useDashboardDate';
import { useLanguage } from '@/hooks/useLanguage';
import type { Language } from '@/contexts/LanguageContext';
import DateSelector from '@/components/date-selector';
import LiveSignalStrip from '@/components/live-signal-strip';
import MastheadPulse from '@/components/masthead-pulse';
import compassIcon from '@/assets/compass-icon.png';

interface DashboardLayoutProps {
  children: React.ReactNode;
}

export default function DashboardLayout({ children }: DashboardLayoutProps) {
  const { user, logout } = useAuth();
  const { currentDate, calendarDate, setCurrentDate, sessionDate } = useDashboardDate();
  const { language, setLanguage } = useLanguage();
  const showLangSwitcher = import.meta.env.VITE_FEATURE_LANG_SWITCHER === 'true';

  const rawName = user?.name && !user.name.includes('@') ? user.name : null;
  const displayName =
    rawName ||
    (user?.email
      ? user.email
          .split('@')[0]
          .replace(/[._-]/g, ' ')
          .replace(/\b\w/g, (c) => c.toUpperCase())
      : 'User');
  const initials = displayName
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((s) => s[0].toUpperCase())
    .join('');

  const now = new Date();

  // On mount/refresh AND every date change, drop the page just below the top
  // utility bar so the masthead title is the first thing the user sees.
  // Instant (not smooth) so the user doesn't perceive a load-time jump.
  // Locking the scroll on the masthead on date change ensures the whole front
  // re-anchors there while the new session's data loads — no mid-page jumps
  // caused by skeletons + actual content swapping heights.
  const mastheadTitleRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    mastheadTitleRef.current?.scrollIntoView({ behavior: 'auto', block: 'start' });
  }, [currentDate]);

  return (
    <div
      className="min-h-screen"
      style={{ background: 'var(--paper)', color: 'var(--ink)' }}
    >
      {/* ===== MASTHEAD ===== */}
      <header
        className="border-b-[3px] border-double"
        style={{ borderColor: 'var(--ink)' }}
      >
        <div className="max-w-7xl mx-auto px-6 md:px-10 pt-3 pb-3">
          {/* Top rule: user (left) · date picker (right) — kept discreet */}
          <div
            className="flex items-center justify-between gap-4 pb-2 mb-4 border-b"
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 9,
              letterSpacing: '0.18em',
              textTransform: 'uppercase',
              borderColor: 'var(--ink)',
              color: 'var(--ink-light)',
            }}
          >
            {/* LEFT: user dropdown */}
            <div className="flex items-center shrink-0">
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <button
                    type="button"
                    aria-label="User menu"
                    className="flex items-center gap-2 hover:opacity-70 transition-opacity min-h-11 min-w-11 px-1"
                  >
                    <Avatar className="h-6 w-6 sm:h-5 sm:w-5">
                      <AvatarImage src={user?.picture} alt={displayName} />
                      <AvatarFallback className="text-[8px]">{initials}</AvatarFallback>
                    </Avatar>
                    <span className="hidden sm:inline">{displayName}</span>
                    <MenuIcon className="h-4 w-4 sm:hidden" />
                  </button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="start">
                  <DropdownMenuLabel className="flex items-center gap-2">
                    <Avatar className="h-7 w-7">
                      <AvatarImage src={user?.picture} alt={displayName} />
                      <AvatarFallback className="text-xs">{initials}</AvatarFallback>
                    </Avatar>
                    <div className="truncate">
                      <p className="text-sm font-medium truncate">{displayName}</p>
                      {user?.email && (
                        <p className="text-xs text-muted-foreground font-normal truncate normal-case">
                          {user.email}
                        </p>
                      )}
                    </div>
                  </DropdownMenuLabel>
                  {showLangSwitcher && (
                    <>
                      <DropdownMenuSeparator />
                      <DropdownMenuRadioGroup
                        value={language}
                        onValueChange={(value) => setLanguage(value as Language)}
                      >
                        <DropdownMenuRadioItem value="fr">FR</DropdownMenuRadioItem>
                        <DropdownMenuRadioItem value="en">EN</DropdownMenuRadioItem>
                      </DropdownMenuRadioGroup>
                    </>
                  )}
                  <DropdownMenuSeparator />
                  <DropdownMenuItem onClick={logout}>
                    <LogOutIcon className="mr-2 h-4 w-4" />
                    Déconnexion
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>

            {/* RIGHT: date picker */}
            <div className="flex items-center shrink-0">
              <DateSelector
                calendarDate={calendarDate}
                onDateChange={setCurrentDate}
                sessionDate={sessionDate ?? undefined}
              />
            </div>
          </div>

          {/* Title block: horizontal lockup desktop, vertical stack on phones */}
          <div
            ref={mastheadTitleRef}
            className="masthead-title flex items-center justify-center gap-6 md:gap-9"
          >
            <div className="masthead-text text-center md:text-right">
              <h1
                className="masthead-wordmark leading-none"
                style={{
                  fontFamily: 'var(--font-display)',
                  fontWeight: 900,
                  fontSize: 'clamp(32px, 7vw, 76px)',
                  letterSpacing: '0.08em',
                  color: 'var(--ink)',
                }}
              >
                COMPASS CC
              </h1>
              <div
                className="masthead-deck mt-2"
                style={{
                  fontFamily: 'var(--font-display)',
                  fontWeight: 400,
                  fontStyle: 'italic',
                  fontSize: 'clamp(14px, 2.6vw, 28px)',
                  letterSpacing: '0.02em',
                  color: 'var(--ink-dark)',
                }}
              >
                The Cocoa Markets Intelligence Briefing
              </div>
            </div>
            <img
              src={compassIcon}
              alt="Compass CC"
              className="masthead-logo shrink-0"
              style={{
                width: 'clamp(56px, 9vw, 104px)',
                height: 'clamp(56px, 9vw, 104px)',
                objectFit: 'contain',
              }}
            />
          </div>
          <style>{`
            @media (max-width: 639px) {
              .masthead-title {
                flex-direction: column-reverse;
                gap: 12px;
              }
              .masthead-text {
                text-align: center !important;
              }
            }
          `}</style>

          {/* Compass Pulse — sparkline + YTD + inline stats, single thin row */}
          <div
            style={{
              marginTop: 12,
              paddingTop: 10,
              borderTop: '1px dotted var(--rule)',
            }}
          >
            <MastheadPulse />
          </div>

          {/* Signal legend (compact, just below title block) */}
          <div
            className="flex flex-col items-center sm:flex-row sm:flex-wrap sm:justify-center gap-2 sm:gap-4 md:gap-8 mt-3 pt-2 border-t uppercase"
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 10,
              letterSpacing: '0.15em',
              borderColor: 'var(--rule)',
              color: 'var(--ink-light)',
            }}
          >
            <span className="inline-flex items-center gap-1.5">
              <span
                className="h-2 w-2 rounded-full"
                style={{ background: 'var(--color-signal-open)' }}
              />
              OPEN — Buy Signal Active
            </span>
            <span className="inline-flex items-center gap-1.5">
              <span
                className="h-2 w-2 rounded-full"
                style={{ background: 'var(--color-signal-monitor)' }}
              />
              MONITOR — Watch & Wait
            </span>
            <span className="inline-flex items-center gap-1.5">
              <span
                className="h-2 w-2 rounded-full"
                style={{ background: 'var(--color-signal-hedge)' }}
              />
              HEDGE — Protect Positions
            </span>
          </div>
        </div>
      </header>

      {/* ===== LIVE TICKER (between masthead and hero) ===== */}
      <div
        className="border-b"
        style={{
          background: 'var(--paper-off)',
          borderColor: 'var(--ink)',
          padding: '8px 0',
        }}
      >
        <div className="max-w-7xl mx-auto px-6 md:px-10 flex items-center">
          <LiveSignalStrip />
        </div>
      </div>

      {/* ===== MAIN ===== */}
      <main className="max-w-7xl mx-auto px-6 md:px-10">{children}</main>

      {/* ===== COLOPHON ===== */}
      <footer
        className="max-w-7xl mx-auto px-6 md:px-10 mt-16 pt-8 pb-10 border-t text-center"
        style={{ borderColor: 'var(--ink)' }}
      >
        <div
          style={{
            fontFamily: 'var(--font-display)',
            fontStyle: 'italic',
            fontSize: 20,
            color: 'var(--ink)',
          }}
        >
          Compass CC
        </div>
        <div
          className="mt-2 uppercase"
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 10,
            letterSpacing: '0.15em',
            color: 'var(--ink-mid)',
          }}
        >
          <UserIcon className="inline h-3 w-3 mr-1.5" />
          {displayName} · {user?.email ?? ''}
        </div>
        <div
          className="mt-3"
          style={{
            fontFamily: 'var(--font-sans)',
            fontSize: 11,
            color: 'var(--ink-light)',
          }}
        >
          © {now.getFullYear()} Compass CC — Cocoa Markets Intelligence
        </div>
      </footer>
    </div>
  );
}
