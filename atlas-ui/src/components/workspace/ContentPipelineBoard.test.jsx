import { render, screen } from "@testing-library/react";
import { describe, expect, test, vi } from "vitest";
import ContentPipelineBoard from "./ContentPipelineBoard";
import ManualArticleForm from "./ManualArticleForm";
import { ToastProvider } from "../../context/ToastContext";

vi.mock("../../services/api", () => ({
  createRun: vi.fn(),
  deleteClient: vi.fn(),
}));

describe("New article overview", () => {
  test("ManualArticleForm renders all fields without crashing", () => {
    render(
      <ToastProvider>
        <ManualArticleForm client="Digimidi.ch" onOpenRun={() => {}} />
      </ToastProvider>
    );
    expect(screen.getByLabelText(/Topic/i)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Create article run/i })
    ).toBeInTheDocument();
  });

  test("ContentPipelineBoard renders for Digimidi.ch", () => {
    render(
      <ToastProvider>
        <ContentPipelineBoard
          client="Digimidi.ch"
          onOpenRun={() => {}}
          onClientDeleted={() => {}}
        />
      </ToastProvider>
    );
    expect(screen.getByText("New article")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Create article run/i })
    ).toBeInTheDocument();
  });
});
