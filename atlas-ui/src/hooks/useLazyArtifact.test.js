import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import * as api from "../services/api";
import {
  clearArtifactCacheForTests,
  invalidateArtifactCache,
  useLazyArtifact,
} from "./useLazyArtifact";

beforeEach(() => {
  clearArtifactCacheForTests();
  vi.restoreAllMocks();
});

test("loads artifact only when enabled", async () => {
  vi.spyOn(api, "getArtifact").mockResolvedValue("hello");

  const { result, rerender } = renderHook(
    ({ enabled }) =>
      useLazyArtifact("c1", "r1", "outline", { enabled }),
    { initialProps: { enabled: false } }
  );

  expect(api.getArtifact).not.toHaveBeenCalled();
  expect(result.current.loading).toBe(false);

  rerender({ enabled: true });

  await waitFor(() => expect(result.current.loading).toBe(false));
  expect(api.getArtifact).toHaveBeenCalledTimes(1);
  expect(result.current.content).toBe("hello");
});

test("reuses cache when revisiting a step", async () => {
  vi.spyOn(api, "getArtifact").mockResolvedValue("cached body");

  const first = renderHook(() =>
    useLazyArtifact("c1", "r1", "draft", { enabled: true })
  );
  await waitFor(() => expect(first.result.current.content).toBe("cached body"));
  first.unmount();

  const second = renderHook(() =>
    useLazyArtifact("c1", "r1", "draft", { enabled: true })
  );
  await waitFor(() => expect(second.result.current.content).toBe("cached body"));
  expect(api.getArtifact).toHaveBeenCalledTimes(1);
});
