import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { Card, CardHeader, CardTitle, CardContent } from "./card";

describe("Card", () => {
  it("renders children", () => {
    render(<Card>test content</Card>);
    expect(screen.getByText("test content")).toBeInTheDocument();
  });

  it("applies custom className", () => {
    const { container } = render(<Card className="custom-class">content</Card>);
    const div = container.firstChild as HTMLElement;
    expect(div.className).toContain("custom-class");
  });
});

describe("CardHeader", () => {
  it("renders children", () => {
    render(<CardHeader>header text</CardHeader>);
    expect(screen.getByText("header text")).toBeInTheDocument();
  });
});

describe("CardTitle", () => {
  it("renders as h3", () => {
    render(<CardTitle>My Title</CardTitle>);
    const title = screen.getByText("My Title");
    expect(title.tagName).toBe("H3");
  });

  it("applies font-semibold class", () => {
    const { container } = render(<CardTitle>Title</CardTitle>);
    expect(container.firstChild).toHaveClass("font-semibold");
  });
});

describe("CardContent", () => {
  it("renders children", () => {
    render(<CardContent>content body</CardContent>);
    expect(screen.getByText("content body")).toBeInTheDocument();
  });
});
