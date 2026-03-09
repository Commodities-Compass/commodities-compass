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
import { useState } from 'react';

interface DateSelectorProps {
  currentDate: string;
  onDateChange: (date: string) => void;
  className?: string;
}

export default function DateSelector({
  currentDate,
  onDateChange,
  className,
}: DateSelectorProps) {
  const [isOpen, setIsOpen] = useState(false);

  const selectedDate = parseISO(currentDate);

  const getNextBusinessDay = (date: Date, direction: 'forward' | 'backward'): Date => {
    const step = direction === 'forward' ? addDays : subDays;
    let next = step(date, 1);
    while (isWeekend(next)) {
      next = step(next, 1);
    }
    return next;
  };

  const handlePrevious = () => {
    const previousBusinessDay = getNextBusinessDay(selectedDate, 'backward');
    onDateChange(format(previousBusinessDay, 'yyyy-MM-dd'));
  };

  const handleNext = () => {
    const nextBusinessDay = getNextBusinessDay(selectedDate, 'forward');
    const today = startOfDay(new Date());
    if (nextBusinessDay <= today) {
      onDateChange(format(nextBusinessDay, 'yyyy-MM-dd'));
    }
  };

  const handleCalendarSelect = (date: Date | undefined) => {
    if (date) {
      onDateChange(format(date, 'yyyy-MM-dd'));
      setIsOpen(false);
    }
  };

  const isNextDisabled = () => {
    const nextBusinessDay = getNextBusinessDay(selectedDate, 'forward');
    return isFuture(nextBusinessDay);
  };

  const disableDate = (date: Date) => {
    return isWeekend(date) || isFuture(date);
  };

  return (
    <Card className={className}>
      <CardContent className="p-4">
        <div className="flex items-center justify-between gap-2">
          <Button
            variant="outline"
            size="icon"
            onClick={handlePrevious}
            aria-label="Previous business day"
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
            aria-label="Next business day"
          >
            <ChevronRightIcon className="h-4 w-4" />
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
