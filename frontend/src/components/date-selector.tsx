import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Calendar } from '@/components/ui/calendar';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';
import { CalendarIcon, ChevronLeftIcon, ChevronRightIcon } from 'lucide-react';
import { format, parseISO, addDays, subDays, isFuture, startOfDay } from 'date-fns';
import { fr } from 'date-fns/locale';
import { useState } from 'react';

interface DateSelectorProps {
  currentDate: string;
  onDateChange: (date: string) => void;
  sessionDate?: string;
  className?: string;
  variant?: 'card' | 'compact';
}

export default function DateSelector({
  currentDate,
  onDateChange,
  sessionDate,
  className,
  variant = 'card',
}: DateSelectorProps) {
  const [isOpen, setIsOpen] = useState(false);

  const selectedDate = parseISO(currentDate);

  const handlePrevious = () => {
    const previous = subDays(selectedDate, 1);
    onDateChange(format(previous, 'yyyy-MM-dd'));
  };

  const handleNext = () => {
    const next = addDays(selectedDate, 1);
    const today = startOfDay(new Date());
    if (next <= today) {
      onDateChange(format(next, 'yyyy-MM-dd'));
    }
  };

  const isNextDisabled = () => isFuture(addDays(selectedDate, 1));

  function handleCalendarSelect(date: Date | undefined) {
    if (date) {
      onDateChange(format(date, 'yyyy-MM-dd'));
      setIsOpen(false);
    }
  }

  if (variant === 'compact') {
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

  return (
    <Card className={className}>
      <CardContent className="p-4">
        <div className="flex items-center justify-between gap-2">
          <Button
            variant="outline"
            size="icon"
            onClick={handlePrevious}
            aria-label="Previous day"
          >
            <ChevronLeftIcon className="h-4 w-4" />
          </Button>

          <Popover open={isOpen} onOpenChange={setIsOpen}>
            <PopoverTrigger asChild>
              <Button
                variant="ghost"
                className="min-w-70 justify-center font-medium hover:bg-accent h-auto px-4 py-1 flex flex-col items-center gap-0"
              >
                <div className="flex items-center gap-2">
                  <CalendarIcon className="h-5 w-5 text-gray-500" />
                  <span>
                    {format(selectedDate, 'EEEE d MMMM yyyy', { locale: fr })}
                  </span>
                </div>
                {sessionDate && sessionDate.slice(0, 10) !== currentDate && (
                  <span className="text-[11px] text-muted-foreground font-normal">
                    Session du {format(parseISO(sessionDate), 'd MMMM yyyy', { locale: fr })}
                  </span>
                )}
              </Button>
            </PopoverTrigger>
            <PopoverContent className="w-auto p-0" align="center">
              <Calendar
                mode="single"
                selected={selectedDate}
                onSelect={handleCalendarSelect}
                disabled={(date) => isFuture(date)}
                defaultMonth={selectedDate}
              />
            </PopoverContent>
          </Popover>

          <Button
            variant="outline"
            size="icon"
            onClick={handleNext}
            disabled={isNextDisabled()}
            aria-label="Next day"
          >
            <ChevronRightIcon className="h-4 w-4" />
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
