import {
  formatStepDurationMs,
  formatStepStatusWithDuration,
  parseIsoTimestamp,
  resolveStepTiming,
} from "./formatStepDuration";

describe("formatStepDurationMs", () => {
  test("formats seconds, minutes, and hours", () => {
    expect(formatStepDurationMs(400)).toBe("<1s");
    expect(formatStepDurationMs(45000)).toBe("45s");
    expect(formatStepDurationMs(135000)).toBe("2m 15s");
    expect(formatStepDurationMs(3660000)).toBe("1h 1m");
  });
});

describe("resolveStepTiming", () => {
  const completed = {
    started_at: "2026-07-12T10:00:00.000Z",
    finished_at: "2026-07-12T10:05:00.000Z",
    duration_ms: 300000,
    status: "done",
  };

  test("running ignores a prior completed record", () => {
    expect(
      resolveStepTiming("outline", { outline: completed }, {}, "running")
    ).toBeNull();
  });

  test("running uses an in-flight server record", () => {
    const active = {
      started_at: "2026-07-12T12:00:00.000Z",
      finished_at: null,
      duration_ms: null,
      status: "running",
    };
    expect(
      resolveStepTiming("outline", { outline: active }, {}, "running")
    ).toEqual({
      started_at: "2026-07-12T12:00:00.000Z",
      finished_at: null,
      duration_ms: null,
      status: "running",
    });
  });

  test("done prefers server duration", () => {
    expect(
      resolveStepTiming("outline", { outline: completed }, { outline: 999 }, "done")
    ).toEqual(completed);
  });
});

describe("formatStepStatusWithDuration", () => {
  test("running elapsed uses UTC timestamps", () => {
    const now = Date.parse("2026-07-12T12:02:30.000Z");
    const text = formatStepStatusWithDuration(
      "running",
      { started_at: "2026-07-12T12:00:00.000Z" },
      now
    );
    expect(text).toBe("Running · 2m 30s");
  });

  test("done shows stored duration", () => {
    expect(
      formatStepStatusWithDuration("done", { duration_ms: 125000 })
    ).toBe("Done · 2m 5s");
  });
});

describe("parseIsoTimestamp", () => {
  test("parses UTC Z suffix", () => {
    expect(parseIsoTimestamp("2026-07-12T12:00:00.000Z")).toBe(
      Date.parse("2026-07-12T12:00:00.000Z")
    );
  });
});
