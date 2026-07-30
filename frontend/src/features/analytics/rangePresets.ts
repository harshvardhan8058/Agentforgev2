/**
 * One-click time ranges for the usage dashboard.
 *
 * The range control is a pair of `datetime-local` inputs, which means the only
 * way to ask "what did we spend this week?" was to work out and type two
 * timestamps in the exact format the input expects. These presets compute both
 * ends instead.
 *
 * Values are produced in the `YYYY-MM-DDTHH:mm` form a `datetime-local` input
 * requires, in **local** time, because that is what the input displays and what
 * the operator means by "last 7 days". `now` is a parameter rather than read
 * from the clock inside, so the mapping is a pure function and testable.
 */

export interface RangePreset {
  readonly label: string;
  /** Returns `[start, end]` as `datetime-local` strings; empty means unbounded. */
  readonly resolve: (now: Date) => readonly [string, string];
}

/** Format a Date as the local `YYYY-MM-DDTHH:mm` a `datetime-local` expects. */
export function toDateTimeLocal(date: Date): string {
  const pad = (n: number): string => String(n).padStart(2, "0");
  return (
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}` +
    `T${pad(date.getHours())}:${pad(date.getMinutes())}`
  );
}

/** Shift `now` back by whole days. */
function daysAgo(now: Date, days: number): Date {
  const shifted = new Date(now);
  shifted.setDate(shifted.getDate() - days);
  return shifted;
}

export const RANGE_PRESETS: readonly RangePreset[] = [
  {
    label: "Last 24 hours",
    resolve: (now) => [toDateTimeLocal(daysAgo(now, 1)), toDateTimeLocal(now)],
  },
  {
    label: "Last 7 days",
    resolve: (now) => [toDateTimeLocal(daysAgo(now, 7)), toDateTimeLocal(now)],
  },
  {
    label: "Last 30 days",
    resolve: (now) => [toDateTimeLocal(daysAgo(now, 30)), toDateTimeLocal(now)],
  },
  {
    label: "Month to date",
    resolve: (now) => [
      toDateTimeLocal(new Date(now.getFullYear(), now.getMonth(), 1, 0, 0)),
      toDateTimeLocal(now),
    ],
  },
  // Both ends blank: the query omits the params entirely, which is the API's
  // "everything" case rather than a very wide explicit range.
  { label: "All time", resolve: () => ["", ""] },
];
