import { render, screen, within } from "@testing-library/react";
import { MetricValueView, ReviewFlagChips, SolverBadge, metricText, Progress } from "@/components/status";
import { flags, metric } from "@/test/fixtures";

test("the five review flags stay separate and are never collapsed into one badge", () => {
  render(<ReviewFlagChips flags={flags} />);
  const list = screen.getByRole("list", { name: /pilot review flags/i });
  const items = within(list).getAllByRole("listitem");
  expect(items).toHaveLength(5);
  expect(list).toHaveTextContent(/Geography\s*reviewed/);
  expect(list).toHaveTextContent(/Rights\s*assumed/);
  expect(list).toHaveTextContent(/Costs\s*referenced/);
  expect(list).toHaveTextContent(/Crop model\s*uncalibrated/);
  expect(list).not.toHaveTextContent(/verified$/i);
});

test("MetricValue renders each status distinctly; null is never zero", () => {
  const { rerender } = render(<MetricValueView metric={metric({ definition_id: "production_kg", value: 152340, unit: "kg" })} />);
  expect(screen.getByText("152.3 t")).toBeInTheDocument();
  rerender(<MetricValueView metric={metric({ definition_id: "basin_saving", value: null, status: "not_estimated", reason: "Return flows not modeled" })} />);
  expect(screen.getByText("Not estimated")).toBeInTheDocument();
  expect(screen.getByText("Return flows not modeled")).toBeInTheDocument();
  rerender(<MetricValueView metric={metric({ definition_id: "productivity", value: null, status: "not_applicable", unit: "kg/m3" })} />);
  expect(screen.getByText("Not applicable")).toBeInTheDocument();
  rerender(<MetricValueView metric={metric({ definition_id: "payback", value: null, status: "blocked", reason: "No crop price" })} />);
  expect(screen.getByText("Blocked")).toBeInTheDocument();
  expect(metricText(metric({ definition_id: "x", value: 0, unit: "kg" }))).toBe("0 kg");
  expect(metricText(null)).toBe("Unavailable");
});

test("solver status copy distinguishes infeasible from unknown", () => {
  render(
    <>
      <SolverBadge status="FEASIBLE" showFriendly />
      <SolverBadge status="INFEASIBLE" showFriendly />
      <SolverBadge status="UNKNOWN" showFriendly />
    </>,
  );
  expect(screen.getByText("Valid plan found; search ended before optimality was proven.")).toBeInTheDocument();
  expect(screen.getByText(/not proof of physical impossibility/i)).toBeInTheDocument();
  expect(screen.getByText(/not a proof of infeasibility/i)).toBeInTheDocument();
});

test("progress without a measured value is indeterminate, never a fake percent", () => {
  const { rerender } = render(<Progress value={null} label="Solve" />);
  expect(screen.getByRole("progressbar")).not.toHaveAttribute("aria-valuenow");
  rerender(<Progress value={0.4} label="Solve" />);
  expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "40");
});
