import { describe, it, expect } from "vitest";
import { cn, formatTimestamp, formatDate } from "./utils";

describe("cn", () => {
  it("merges class names", () => {
    expect(cn("foo", "bar")).toBe("foo bar");
  });

  it("handles conditional classes", () => {
    expect(cn("base", false && "no", true && "yes")).toBe("base yes");
  });

  it("deduplicates tailwind classes", () => {
    expect(cn("p-2", "p-4")).toBe("p-4");
  });

  it("handles empty inputs", () => {
    expect(cn()).toBe("");
  });
});

describe("formatTimestamp", () => {
  it("returns dash for null", () => {
    expect(formatTimestamp(null)).toBe("-");
  });

  it("returns dash for undefined", () => {
    expect(formatTimestamp(undefined)).toBe("-");
  });

  it("returns dash for empty string", () => {
    expect(formatTimestamp("")).toBe("-");
  });

  it("returns dash for invalid date", () => {
    expect(formatTimestamp("not-a-date")).toBe("-");
  });

  it("formats valid ISO timestamp", () => {
    const result = formatTimestamp("2026-08-16T10:00:00+07:00");
    expect(result).toContain("2026");
    expect(result).toContain("16");
    // Should not be a dash
    expect(result).not.toBe("-");
  });
});

describe("formatDate", () => {
  it("returns dash for null", () => {
    expect(formatDate(null)).toBe("-");
  });

  it("returns dash for invalid date", () => {
    expect(formatDate("invalid")).toBe("-");
  });

  it("formats valid ISO date", () => {
    const result = formatDate("2026-08-16T10:00:00+07:00");
    expect(result).toContain("2026");
    expect(result).not.toBe("-");
  });
});
