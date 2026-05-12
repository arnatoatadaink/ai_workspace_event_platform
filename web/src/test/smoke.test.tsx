import { render, screen } from "@testing-library/react";

function Hello({ name }: { name: string }): JSX.Element {
  return <p>Hello, {name}</p>;
}

describe("Vitest smoke test", () => {
  it("renders a React component", () => {
    render(<Hello name="Vitest" />);
    expect(screen.getByText("Hello, Vitest")).toBeInTheDocument();
  });
});
