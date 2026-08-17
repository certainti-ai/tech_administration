import type { IsoDate } from "./types";

const MS_PER_DAY = 86_400_000;
const ISO_DATE = /^(\d{4})-(\d{2})-(\d{2})$/;

/**
 * Parse a `YYYY-MM-DD` calendar date to the UTC-midnight instant that
 * represents it. Parsing explicitly (rather than via `new Date(string)`) keeps
 * the result identical regardless of the host timezone.
 */
export function parseIsoDate(value: IsoDate): number {
  const match = ISO_DATE.exec(value);
  if (!match) {
    throw new TypeError(`Expected a YYYY-MM-DD date, received "${value}"`);
  }
  const [, year, month, day] = match as unknown as [string, string, string, string];
  return Date.UTC(Number(year), Number(month) - 1, Number(day));
}

/** Collapse an instant to the UTC-midnight instant of the day it falls on. */
export function startOfUtcDay(instant: Date): number {
  return Date.UTC(
    instant.getUTCFullYear(),
    instant.getUTCMonth(),
    instant.getUTCDate(),
  );
}

/**
 * Whole days from `today` until `date`. Negative when the date has passed,
 * zero when it is today.
 */
export function daysUntil(date: IsoDate, today: Date): number {
  return Math.round((parseIsoDate(date) - startOfUtcDay(today)) / MS_PER_DAY);
}

/** Format a calendar date for display, e.g. `17 Aug 2026`. */
export function formatIsoDate(date: IsoDate): string {
  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  }).format(parseIsoDate(date));
}

/** Render a day offset as human text, e.g. `in 12 days`, `today`, `3 days ago`. */
export function describeDayOffset(days: number): string {
  if (days === 0) return "today";
  if (days === 1) return "tomorrow";
  if (days === -1) return "yesterday";
  return days > 0 ? `in ${days} days` : `${Math.abs(days)} days ago`;
}
