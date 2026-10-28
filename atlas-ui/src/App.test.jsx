import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import * as api from "./services/api";
import App from "./App";

beforeEach(() => {
  vi.spyOn(api, "getAuthToken").mockReturnValue("test-token");
  vi.spyOn(api, "getMe").mockResolvedValue({ username: "admin", role: "admin" });
  vi.spyOn(api, "getClients").mockResolvedValue([]);
  vi.spyOn(api, "getContextFilesCatalog").mockResolvedValue([]);
});

afterEach(() => {
  vi.restoreAllMocks();
});

test("renders workspace list after auth", async () => {
  render(<App />);
  await waitFor(() => {
    expect(screen.getByText(/workspaces/i)).toBeInTheDocument();
  });
});

test("shows login when no session", async () => {
  api.getAuthToken.mockReturnValue(null);
  render(<App />);
  await waitFor(() => {
    expect(screen.getByRole("button", { name: /sign in/i })).toBeInTheDocument();
  });
});
