import { render, screen } from "@testing-library/react";
import { App } from "./App";

test("renders the shell", () => {
  globalThis.fetch = vi.fn(() => new Promise<Response>(() => {}));
  render(<App />);
  expect(screen.getByRole("heading", { name: "AabFlow" })).toBeInTheDocument();
});
