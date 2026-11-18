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

test("identifies a fact-check contract failure separately from French errors", async () => {
  api.getQualityDiagnostic.mockResolvedValue({ kind: "rejected", check: "fact_check", content: '{"issues":', message: "JSON incomplete", issues: [] });
  render(<QualityDiagnostic client="c" runId="r" stepName="fact_check" />);
  await screen.findByText(/Fact-check output could not be validated/);
  expect(screen.queryByText(/failed the French check/)).toBeNull();
});

test("shows early draft signals as advisory findings", async () => {
  api.getQualityDiagnostic.mockResolvedValue({kind: "draft_preflight", issues: [{message:"Verify a potentially truncated surname.",severity:"warning"}]});
  render(<QualityDiagnostic client="c" runId="r" stepName="draft" />);
  await screen.findByText(/Draft findings to review/);
  await screen.findByText(/Verify a potentially truncated surname/);
});
