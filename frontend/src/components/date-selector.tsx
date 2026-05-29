import { Calendar } from '@/components/ui/calendar';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';
import { CalendarIcon } from 'lucide-react';
import { format, parseISO, isFuture } from 'date-fns';
import { fr } from 'date-fns/locale';
import { useState } from 'react';

interface DateSelectorProps {
  currentDate: string;
  onDateChange: (date: string) => void;
  sessionDate?: string;
  className?: string;
}

export default function DateSelector({
  currentDate,
  onDateChange,
  sessionDate,
  className,
}: DateSelectorProps) {
  const [isOpen, setIsOpen] = useState(false);
  const selectedDate = parseISO(currentDate);

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
            aria-label="Select session date"
          >
            <CalendarIcon style={{ width: 12, height: 12 }} />
            <span style={{ color: 'var(--ink)', fontWeight: 600 }}>
              {format(selectedDate, 'd MMM yyyy', { locale: fr })}
            </span>
            {sessionDate && sessionDate.slice(0, 10) !== currentDate && (
              <span style={{ color: 'var(--ink-light)' }}>
                · session {format(parseISO(sessionDate), 'd MMM', { locale: fr })}
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
