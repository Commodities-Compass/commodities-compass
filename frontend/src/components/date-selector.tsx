import { Calendar } from '@/components/ui/calendar';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';
import { CalendarIcon } from 'lucide-react';
import { format, parseISO, isFuture } from 'date-fns';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useLanguage } from '@/hooks/useLanguage';
import { formatDate } from '@/utils/format-locale';

interface DateSelectorProps {
  /** Date displayed on the trigger pill + highlighted in the popover (= today's real date by default; or whatever the user has picked). */
  calendarDate: string;
  /** Backend-resolved session date — shown as "· session X" suffix when ≠ calendarDate. */
  sessionDate?: string;
  onDateChange: (date: string) => void;
  className?: string;
}

export default function DateSelector({
  calendarDate,
  onDateChange,
  sessionDate,
  className,
}: DateSelectorProps) {
  const { t } = useTranslation();
  const { language } = useLanguage();
  const [isOpen, setIsOpen] = useState(false);
  const selectedDate = parseISO(calendarDate);

  function handleCalendarSelect(date: Date | undefined) {
    if (date) {
      onDateChange(format(date, 'yyyy-MM-dd'));
      setIsOpen(false);
    }
  }

  return (
    <>
      <style>{`.editorial-date-btn:hover { color: var(--ink) !important; }`}</style>
      <Popover open={isOpen} onOpenChange={setIsOpen}>
        <PopoverTrigger asChild>
          <button
            type="button"
            className={`editorial-date-btn ${className ?? ''}`.trim()}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 6,
              fontFamily: 'var(--font-mono)',
              fontSize: 10,
              letterSpacing: '0.15em',
              textTransform: 'uppercase',
              color: 'var(--ink-mid)',
              background: 'transparent',
              border: 'none',
              cursor: 'pointer',
              padding: '8px 10px',
              minHeight: 36,
              transition: 'color 120ms',
            }}
            aria-label={t('common.select_session_date')}
          >
            <CalendarIcon style={{ width: 12, height: 12 }} />
            <span style={{ color: 'var(--ink)', fontWeight: 600 }}>
              {formatDate(selectedDate, language, 'd MMM yyyy')}
            </span>
            {sessionDate && sessionDate.slice(0, 10) !== calendarDate && (
              <span style={{ color: 'var(--ink-light)' }}>
                {t('common.session_prefix')} {formatDate(parseISO(sessionDate), language, 'd MMM')}
              </span>
            )}
          </button>
        </PopoverTrigger>
        <PopoverContent
          className="w-auto p-0"
          align="end"
          sideOffset={6}
          collisionPadding={16}
          style={{
            background: 'var(--paper)',
            border: '1px solid var(--ink)',
            borderRadius: 0,
            boxShadow: '0 8px 24px rgba(0, 0, 0, 0.08)',
          }}
        >
          <Calendar
            mode="single"
            selected={selectedDate}
            onSelect={handleCalendarSelect}
            disabled={(date) => isFuture(date)}
            defaultMonth={selectedDate}
          />
        </PopoverContent>
      </Popover>
    </>
  );
}
