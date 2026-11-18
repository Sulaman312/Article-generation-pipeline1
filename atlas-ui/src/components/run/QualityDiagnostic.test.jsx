import React from "react";
import { render, screen } from "@testing-library/react";
import { vi, test, expect } from "vitest";
import * as api from "../../services/api";
import QualityDiagnostic from "./QualityDiagnostic";
vi.mock("../../services/api", () => ({ getQualityDiagnostic: vi.fn() }));

test("shows rejected output safely and highlights every offending occurrence", async () => {
  api.getQualityDiagnostic.mockResolvedValue({ kind: "rejected", content: "This is <script>alert(1)</script>. This.", issues: [{term: "This", severity: "error"}] });
  const { container } = render(<QualityDiagnostic client="c" runId="r" stepName="outline" />);
  await screen.findByText(/This output failed/);
  expect(container.querySelectorAll("mark")).toHaveLength(2);
  expect(container.querySelector("script")).toBeNull();
  expect(container.querySelector("pre").textContent).toContain("<script>");
});

test("shows source-specific preflight findings", async () => {
  api.getQualityDiagnostic.mockResolvedValue({kind: "preflight", issues: [{source: "input:Notes",term:"hero",suggestion:"image principale",severity:"warning"}]});
  render(<QualityDiagnostic client="c" runId="r" stepName="topic_card" />);
  await screen.findByText(/input:Notes: hero/);
});
