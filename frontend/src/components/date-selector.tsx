import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Calendar } from '@/components/ui/calendar';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';
import { CalendarIcon, ChevronLeftIcon, ChevronRightIcon } from 'lucide-react';
import { format, parseISO, addDays, subDays, isWeekend, isFuture, startOfDay } from 'date-fns';
import { useState, useMemo } from 'react';

interface DateSelectorProps {
  currentDate: string;
  onDateChange: (date: string) => void;
  nonTradingDays?: Set<string>;
  className?: string;
}

export default function DateSelector({
  currentDate,
  onDateChange,
  nonTradingDays,
  className,
}: DateSelectorProps) {
  const [isOpen, setIsOpen] = useState(false);

  const selectedDate = parseISO(currentDate);

  const isNonTradingDay = useMemo(() => {
    return (d: Date) => {
      if (isWeekend(d)) return true;
      if (!nonTradingDays || nonTradingDays.size === 0) return false;
      return nonTradingDays.has(format(d, 'yyyy-MM-dd'));
    };
  }, [nonTradingDays]);

  const getNextTradingDay = (date: Date, direction: 'forward' | 'backward'): Date => {
    const step = direction === 'forward' ? addDays : subDays;
    let next = step(date, 1);
    // Safety limit to avoid infinite loops (max 30 days skip)
    let guard = 0;
    while (isNonTradingDay(next) && guard < 30) {
      next = step(next, 1);
      guard++;
    }
    return next;
  };

  const handlePrevious = () => {
    const previousTradingDay = getNextTradingDay(selectedDate, 'backward');
    onDateChange(format(previousTradingDay, 'yyyy-MM-dd'));
  };

  const handleNext = () => {
    const nextTradingDay = getNextTradingDay(selectedDate, 'forward');
    const today = startOfDay(new Date());
    if (nextTradingDay <= today) {
      onDateChange(format(nextTradingDay, 'yyyy-MM-dd'));
    }
  };

  const isNextDisabled = () => {
    const nextTradingDay = getNextTradingDay(selectedDate, 'forward');
    return isFuture(nextTradingDay);
  };

  const disableDate = (date: Date) => {
    return isNonTradingDay(date) || isFuture(date);
  };

  return (
    <Card className={className}>
      <CardContent className="p-4">
        <div className="flex items-center justify-between gap-2">
          <Button
            variant="outline"
            size="icon"
            onClick={handlePrevious}
            aria-label="Previous trading day"
          >
            <ChevronLeftIcon className="h-4 w-4" />
          </Button>

          <Popover open={isOpen} onOpenChange={setIsOpen}>
            <PopoverTrigger asChild>
              <Button
                variant="ghost"
                className="min-w-[280px] justify-center font-medium hover:bg-accent h-10 px-4 flex items-center gap-2"
              >
                <CalendarIcon className="h-5 w-5 text-gray-500" />
                <span>
                  {format(selectedDate, 'EEEE, MMMM d, yyyy')}
                </span>
              </Button>
            </PopoverTrigger>
            <PopoverContent className="w-auto p-0" align="center">
              <Calendar
                mode="single"
                selected={selectedDate}
                onSelect={handleCalendarSelect}
                disabled={disableDate}
                defaultMonth={selectedDate}
              />
            </PopoverContent>
          </Popover>

          <Button
            variant="outline"
            size="icon"
            onClick={handleNext}
            disabled={isNextDisabled()}
            aria-label="Next trading day"
          >
            <ChevronRightIcon className="h-4 w-4" />
          </Button>
        </div>
      </CardContent>
    </Card>
  );

  function handleCalendarSelect(date: Date | undefined) {
    if (date) {
      onDateChange(format(date, 'yyyy-MM-dd'));
      setIsOpen(false);
    }
  }
}
