/**
 * `formatWhen`: a short, human-readable rendering of a past timestamp.
 *
 * History lists previously showed raw ISO-8601 strings such as
 * `2026-07-29T07:18:17.352299+00:00`, which is precise, unreadable, and wider than the
 * column holding it. Relative phrasing answers the question a history list actually
 * raises — "how recent is this?" — while older entries fall back to an absolute date,
 * since "412 days ago" is not useful.
 *
 * Pure, with `now` injectable, so the mapping is testable without freezing the clock.
 */

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

/** Beyond this age a calendar date is more informative than a relative phrase. */
const ABSOLUTE_AFTER_MS = 7 * DAY;

export function formatWhen(iso: string, now: Date = new Date()): string {
  const then = new Date(iso);
  // Never fabricate a date: an unparseable value is returned as given so the problem
  // is visible rather than silently rendered as "just now".
  if (Number.isNaN(then.getTime())) return iso;

  const elapsed = now.getTime() - then.getTime();

  // A clock skew between server and browser can put a timestamp slightly ahead;
  // "just now" is truer than a negative age.
  if (elapsed < MINUTE) return "just now";

  if (elapsed < HOUR) {
    const minutes = Math.floor(elapsed / MINUTE);
    return `${minutes} minute${minutes === 1 ? "" : "s"} ago`;
  }
  if (elapsed < DAY) {
    const hours = Math.floor(elapsed / HOUR);
    return `${hours} hour${hours === 1 ? "" : "s"} ago`;
  }
  if (elapsed < ABSOLUTE_AFTER_MS) {
    const days = Math.floor(elapsed / DAY);
    return `${days} day${days === 1 ? "" : "s"} ago`;
  }

  return then.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}
