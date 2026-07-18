import type { ButtonHTMLAttributes, ReactNode } from "react";

export function IconButton(props: ButtonHTMLAttributes<HTMLButtonElement> & {
  label: string;
  children: ReactNode;
  variant?: "default" | "danger";
}) {
  const { label, children, variant = "default", className = "", ...buttonProps } = props;
  return (
    <button
      type="button"
      aria-label={label}
      title={buttonProps.title ?? label}
      className={`rm-icon-button ${variant === "danger" ? "danger" : ""} ${className}`}
      {...buttonProps}
    >
      {children}
    </button>
  );
}
