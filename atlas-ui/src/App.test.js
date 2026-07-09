import { render, screen, waitFor } from "@testing-library/react";
import * as api from "./services/api";
import App from "./App";

beforeEach(() => {
  jest.spyOn(api, "getClients").mockResolvedValue([]);
  jest.spyOn(api, "getContextFilesCatalog").mockResolvedValue([]);
});

afterEach(() => {
  jest.restoreAllMocks();
});

test("renders workspace list after pipeline loads", async () => {
  render(<App />);
  await waitFor(() => {
    expect(screen.getByText(/workspaces/i)).toBeInTheDocument();
  });
});
