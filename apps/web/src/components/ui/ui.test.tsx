import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { THEME_KEY, themeScript } from "@/lib/theme-script";

import {
  Button,
  Drawer,
  DrawerHeader,
  IconButton,
  Segment,
  SegmentedControl,
  Tabs,
  ThemeToggle,
  toast,
  Toaster,
  Tooltip,
  useToastStore,
} from ".";

describe("component kit", () => {
  it("Button keeps its accessible name while loading and cannot be clicked", async () => {
    const onClick = vi.fn();
    render(
      <Button loading onClick={onClick}>
        Save version
      </Button>,
    );
    const button = screen.getByRole("button", { name: "Save version" });
    expect(button).toBeDisabled();
    await userEvent.click(button);
    expect(onClick).not.toHaveBeenCalled();
  });

  it("IconButton is named by its label and reports its pressed state", () => {
    render(
      <IconButton label="Hide the left panel" pressed>
        <svg />
      </IconButton>,
    );
    expect(screen.getByRole("button", { name: "Hide the left panel" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("SegmentedControl is a named group of toggle buttons", async () => {
    const onPlan = vi.fn();
    render(
      <SegmentedControl label="View mode">
        <Segment active onClick={() => undefined}>
          3D model
        </Segment>
        <Segment active={false} onClick={onPlan}>
          Floor plan
        </Segment>
      </SegmentedControl>,
    );
    expect(screen.getByRole("group", { name: "View mode" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "3D model" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await userEvent.click(screen.getByRole("button", { name: "Floor plan" }));
    expect(onPlan).toHaveBeenCalled();
  });

  it("Tabs expose a tablist with the selected tab", async () => {
    const onChange = vi.fn();
    render(
      <Tabs
        label="How to create the design"
        items={[
          { value: "ai", label: "Describe with AI" },
          { value: "form", label: "Specification form" },
        ]}
        value="ai"
        onChange={onChange}
      />,
    );
    expect(screen.getByRole("tab", { name: "Describe with AI" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    await userEvent.click(screen.getByRole("tab", { name: "Specification form" }));
    expect(onChange).toHaveBeenCalledWith("form");
  });

  it("Drawer is a named region whose header closes it", async () => {
    const onClose = vi.fn();
    render(
      <Drawer label="Design report">
        <DrawerHeader title="Design report" onClose={onClose} closeLabel="Close report" />
      </Drawer>,
    );
    expect(screen.getByRole("complementary", { name: "Design report" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Close report" }));
    expect(onClose).toHaveBeenCalled();
  });

  it("Tooltip text is only in the document while the trigger is hovered or focused", async () => {
    render(
      <Tooltip content="Switch to dark theme">
        <button type="button">Theme</button>
      </Tooltip>,
    );
    expect(screen.queryByRole("tooltip")).toBeNull();
    await userEvent.hover(screen.getByRole("button", { name: "Theme" }));
    expect(screen.getByRole("tooltip")).toHaveTextContent("Switch to dark theme");
    await userEvent.unhover(screen.getByRole("button", { name: "Theme" }));
    expect(screen.queryByRole("tooltip")).toBeNull();
  });
});

describe("toasts", () => {
  beforeEach(() => useToastStore.setState({ items: [] }));

  it("shows a message, lets it be dismissed, and removes it after its lifetime", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    render(<Toaster />);
    act(() => toast.success("Version v3 is now open"));
    expect(screen.getByText("Version v3 is now open")).toBeInTheDocument();
    act(() => toast.error("Download failed: no canvas"));
    await userEvent.click(screen.getAllByRole("button", { name: "Dismiss notification" })[1]!);
    expect(screen.queryByText("Download failed: no canvas")).toBeNull();
    act(() => vi.advanceTimersByTime(4100));
    expect(screen.queryByText("Version v3 is now open")).toBeNull();
    vi.useRealTimers();
  });

  it("keeps at most four toasts", () => {
    render(<Toaster />);
    act(() => {
      for (let i = 1; i <= 6; i++) toast.info(`Message ${i}`);
    });
    expect(screen.queryByText("Message 2")).toBeNull();
    expect(screen.getByText("Message 6")).toBeInTheDocument();
  });
});

describe("theme", () => {
  beforeEach(() => {
    window.localStorage.clear();
    delete document.documentElement.dataset.theme;
  });

  it("toggles light and dark, applies it to <html> and remembers the choice", async () => {
    render(<ThemeToggle />);
    await userEvent.click(screen.getByRole("button", { name: "Switch to dark theme" }));
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(window.localStorage.getItem(THEME_KEY)).toBe("dark");
    await userEvent.click(screen.getByRole("button", { name: "Switch to light theme" }));
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(window.localStorage.getItem(THEME_KEY)).toBe("light");
  });

  it("the pre-paint script applies the stored choice, else the system setting", () => {
    window.localStorage.setItem(THEME_KEY, "dark");
    new Function(themeScript)();
    expect(document.documentElement.dataset.theme).toBe("dark");
    window.localStorage.clear();
    new Function(themeScript)(); // jsdom has no matchMedia: falls back to light
    expect(document.documentElement.dataset.theme).toBe("light");
  });
});
