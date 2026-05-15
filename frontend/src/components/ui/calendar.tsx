import * as React from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { DayPicker } from "react-day-picker";

import { cn } from "@/utils";

export type CalendarProps = React.ComponentProps<typeof DayPicker>;

/**
 * Editorial Calendar — magazine aesthetic:
 *  - Mono uppercase weekday headers
 *  - Playfair italic month/year caption
 *  - Sharp corners, ink/paper palette
 *  - Selected day: solid ink bg, paper text
 *  - Today: 1px ink ring
 *  - Disabled: ink-light at low opacity
 */
function Calendar({
  className,
  classNames,
  showOutsideDays = true,
  ...props
}: CalendarProps) {
  return (
    <DayPicker
      showOutsideDays={showOutsideDays}
      className={cn("p-4 editorial-calendar", className)}
      classNames={{
        months: "flex flex-col sm:flex-row gap-4",
        month: "space-y-3",
        month_caption:
          "relative flex justify-center items-center pb-2 mb-1 border-b border-[var(--rule)]",
        caption_label:
          "[font-family:var(--font-display)] italic text-[18px] leading-none text-[var(--ink)]",
        nav: "flex items-center",
        button_previous:
          "absolute left-0 top-0 h-7 w-7 inline-flex items-center justify-center text-[var(--ink-mid)] hover:text-[var(--ink)] transition-colors disabled:opacity-30 disabled:cursor-not-allowed",
        button_next:
          "absolute right-0 top-0 h-7 w-7 inline-flex items-center justify-center text-[var(--ink-mid)] hover:text-[var(--ink)] transition-colors disabled:opacity-30 disabled:cursor-not-allowed",
        month_grid: "w-full border-collapse",
        weekdays: "flex",
        weekday:
          "w-9 [font-family:var(--font-mono)] uppercase text-[9px] font-semibold tracking-[0.18em] text-[var(--ink-light)] pb-2",
        week: "flex w-full mt-1",
        day: "relative p-0 text-center focus-within:relative focus-within:z-20",
        day_button:
          "h-9 w-9 inline-flex items-center justify-center [font-family:var(--font-mono)] text-[12px] font-medium tabular-nums text-[var(--ink-dark)] hover:bg-[var(--paper-off)] cursor-pointer transition-colors",
        selected:
          "[&_button]:!bg-[var(--ink)] [&_button]:!text-[var(--paper)] [&_button]:!font-semibold",
        today:
          "[&_button]:ring-1 [&_button]:ring-[var(--ink)] [&_button]:ring-inset",
        outside: "[&_button]:text-[var(--ink-light)] [&_button]:opacity-60",
        disabled:
          "[&_button]:!text-[var(--ink-light)] [&_button]:!opacity-30 [&_button]:!cursor-not-allowed [&_button]:!bg-transparent",
        hidden: "invisible",
        ...classNames,
      }}
      components={{
        Chevron: ({ orientation, className: chevronClassName, ...chevronProps }) => {
          const Icon = orientation === "left" ? ChevronLeft : ChevronRight;
          return <Icon className={cn("h-4 w-4", chevronClassName)} {...chevronProps} />;
        },
      }}
      {...props}
    />
  );
}
Calendar.displayName = "Calendar";

export { Calendar };
