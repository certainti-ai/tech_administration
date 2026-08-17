import { describe, expect, it } from "vitest";
import {
  daysUntil,
  describeDayOffset,
  formatIsoDate,
  parseIsoDate,
  startOfUtcDay,
} from "@/lib/dates";

describe("parseIsoDate", () => {
  it("parses a calendar date to UTC midnight", () => {
    expect(parseIsoDate("2026-08-17")).toBe(Date.UTC(2026, 7, 17));
  });

  it("rejects anything that is not YYYY-MM-DD", () => {
    expect(() => parseIsoDate("17/08/2026")).toThrow(TypeError);
    expect(() => parseIsoDate("2026-8-7")).toThrow(TypeError);
    expect(() => parseIsoDate("")).toThrow(TypeError);
  });
});

describe("startOfUtcDay", () => {
  it("drops the time component", () => {
    expect(startOfUtcDay(new Date("2026-08-17T23:59:59.999Z"))).toBe(
      Date.UTC(2026, 7, 17),
    );
  });
});

describe("daysUntil", () => {
  const today = new Date("2026-08-17T12:00:00.000Z");

  it("returns zero on the day itself, regardless of time of day", () => {
    expect(daysUntil("2026-08-17", today)).toBe(0);
    expect(daysUntil("2026-08-17", new Date("2026-08-17T00:00:00.000Z"))).toBe(0);
    expect(daysUntil("2026-08-17", new Date("2026-08-17T23:59:00.000Z"))).toBe(0);
  });

  it("counts forward and backward", () => {
    expect(daysUntil("2026-08-31", today)).toBe(14);
    expect(daysUntil("2026-08-10", today)).toBe(-7);
  });

  it("crosses month and year boundaries", () => {
    expect(daysUntil("2026-09-01", today)).toBe(15);
    expect(daysUntil("2027-01-01", today)).toBe(137);
  });

  it("is unaffected by daylight-saving transitions", () => {
    // Spans the late-March European DST shift; still exactly 14 calendar days.
    const march = new Date("2027-03-21T00:00:00.000Z");
    expect(daysUntil("2027-04-04", march)).toBe(14);
  });
});

describe("describeDayOffset", () => {
  it("uses relative words near zero", () => {
    expect(describeDayOffset(0)).toBe("today");
    expect(describeDayOffset(1)).toBe("tomorrow");
    expect(describeDayOffset(-1)).toBe("yesterday");
  });

  it("counts days either side", () => {
    expect(describeDayOffset(12)).toBe("in 12 days");
    expect(describeDayOffset(-3)).toBe("3 days ago");
  });
});

describe("formatIsoDate", () => {
  it("renders in UTC so the calendar date never shifts", () => {
    expect(formatIsoDate("2026-08-17")).toBe("17 Aug 2026");
    expect(formatIsoDate("2026-01-01")).toBe("1 Jan 2026");
  });
});
