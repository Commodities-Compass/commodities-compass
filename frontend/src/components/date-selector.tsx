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
}

export default function DateSelector({
  currentDate,
  onDateChange,
  sessionDate,
  className,
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

  const isNextDisabled = () => {
    return isFuture(addDays(selectedDate, 1));
  };

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
                className="min-w-[280px] justify-center font-medium hover:bg-accent h-auto px-4 py-1 flex flex-col items-center gap-0"
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

  function handleCalendarSelect(date: Date | undefined) {
    if (date) {
      onDateChange(format(date, 'yyyy-MM-dd'));
      setIsOpen(false);
    }
  }
}
