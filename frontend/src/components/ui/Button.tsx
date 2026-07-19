/**
 * `Button`: token-styled button primitive.
 *
 * Variants and sizes resolve entirely to design tokens via Tailwind utilities.
 * Renders a native `<button>` (accessible name from its children/`aria-label`),
 * with a visible focus ring and an optional in-button loading state.
 */
import { forwardRef, type ButtonHTMLAttributes } from "react";

import { cn } from "../../lib/cn";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
export type ButtonSize = "sm" | "md" | "lg" | "xl" | "icon";

const VARIANT_CLASSES: Record<ButtonVariant, string> = {
  primary:
    "bg-primary text-primary-fg shadow-elevation-1 hover:bg-primary-hover active:translate-y-px",
  secondary:
    "bg-surface-raised text-text border border-border hover:border-border-strong hover:bg-surface-hover",
  ghost: "bg-transparent text-text-muted hover:bg-surface-hover hover:text-text",
  danger: "bg-danger text-white shadow-elevation-1 hover:opacity-90 active:translate-y-px",
};

const SIZE_CLASSES: Record<ButtonSize, string> = {
  sm: "h-8 px-3 text-sm rounded-md gap-1.5",
  md: "h-10 px-4 text-sm rounded-md gap-2",
  lg: "h-11 px-5 text-base rounded-lg gap-2",
  xl: "h-12 px-6 text-base rounded-lg gap-2.5",
  icon: "h-9 w-9 rounded-md",
};

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "primary", size = "md", loading = false, className, children, disabled, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      className={cn(
        "inline-flex items-center justify-center font-medium transition-[background-color,border-color,color,box-shadow,transform,opacity] duration-fast ease-standard",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus-ring focus-visible:ring-offset-2 focus-visible:ring-offset-bg",
        "disabled:cursor-not-allowed disabled:opacity-50 disabled:shadow-none disabled:active:translate-y-0",
        VARIANT_CLASSES[variant],
        SIZE_CLASSES[size],
        className,
      )}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...rest}
    >
      {loading && (
        <span
          className="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent"
          data-testid="button-spinner"
          aria-hidden="true"
        />
      )}
      {children}
    </button>
  );
});
