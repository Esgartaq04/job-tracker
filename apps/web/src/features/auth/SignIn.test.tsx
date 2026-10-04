import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SignIn } from "./SignIn";

describe("SignIn title screen", () => {
  it("hides the form until START is pressed", () => {
    render(<SignIn onSignedIn={() => {}} />);
    expect(screen.queryByLabelText("Email")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /press start/i }));

    expect(screen.getByLabelText("Email")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Select Profile" })).toBeInTheDocument();
  });

  it("starts on Enter when focus is not on a button", () => {
    render(<SignIn onSignedIn={() => {}} />);
    fireEvent.keyDown(document.body, { key: "Enter" });
    expect(screen.getByLabelText("Email")).toBeInTheDocument();
  });

  it("goes back to the title screen", () => {
    render(<SignIn onSignedIn={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: /press start/i }));
    fireEvent.click(screen.getByRole("button", { name: /back/i }));
    expect(screen.getByRole("button", { name: /press start/i })).toBeInTheDocument();
  });
});
