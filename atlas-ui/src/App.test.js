import { render, screen } from "@testing-library/react";
import App from "./App";

test("renders idle state", () => {
  render(<App />);
  expect(
    screen.getByText(/select a run or start a new one/i)
  ).toBeInTheDocument();
});
