import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import DashboardPage from "@/app/dashboard/page";
import { mockDashboardState } from "@/lib/mock";
import { pct, toneForSigned } from "@/lib/format";
import { DashboardState } from "@/lib/schemas";

describe("dashboard mock state", () => {
  it("has a break-even of ~55.56% for payout 0.80", () => {
    const s = mockDashboardState();
    expect(s.break_even).toBeCloseTo(1 / 1.8, 6);
    // thresholds derive from break-even + margin; PUT is symmetric
    expect(s.threshold_put).toBeCloseTo(1 - s.threshold_call, 6);
  });

  it("validates against the zod schema", () => {
    expect(() => DashboardState.parse(mockDashboardState())).not.toThrow();
  });

  it("current action is NO_TRADE with a reason when model unavailable", () => {
    const s = mockDashboardState();
    expect(s.current_action).toBe("NO_TRADE");
    expect(s.no_trade_reason).toBe("MODEL_UNAVAILABLE");
  });
});

describe("formatting helpers", () => {
  it("pct handles null and numbers", () => {
    expect(pct(null)).toBe("—");
    expect(pct(0.5556)).toBe("55.56%");
  });
  it("tone reflects sign", () => {
    expect(toneForSigned(1)).toBe("pos");
    expect(toneForSigned(-1)).toBe("neg");
    expect(toneForSigned(null)).toBe("muted");
  });
});

describe("dashboard render", () => {
  it("renders the kill switch and key cards", () => {
    render(<DashboardPage />);
    expect(screen.getByText("Break-even")).toBeDefined();
    expect(screen.getByText("Balance")).toBeDefined();
    // real-execution-disabled reassurance must be visible
    expect(screen.getByText("deshabilitada")).toBeDefined();
  });
});
