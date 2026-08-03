/**
 * `Card`: a token-styled surface container with optional raised elevation.
 * Composed of `Card`, `CardHeader`, `CardTitle`, and `CardContent`.
 */
import type { JSX } from "react";
import { type HTMLAttributes } from "react";

import { cn } from "../../lib/cn";

export function Card({
  className,
  raised = false,
  interactive = false,
  ...rest
}: HTMLAttributes<HTMLDivElement> & {
  raised?: boolean;
  interactive?: boolean;
}): JSX.Element {
  return (
    <div
      className={cn(
        "rounded-lg border border-border bg-surface",
        raised ? "bg-surface-raised shadow-elevation-2" : "shadow-elevation-1",
        interactive && "af-interactive cursor-pointer",
        className,
      )}
      {...rest}
    />
  );
}

export function CardHeader({
  className,
  ...rest
}: HTMLAttributes<HTMLDivElement>): JSX.Element {
  return <div className={cn("flex flex-col gap-1 p-6", className)} {...rest} />;
}

export function CardTitle({
  className,
  children,
  /**
   * Heading level to render. Defaults to `h3`, which is right for a card nested under a
   * section heading — but a card that is itself a top-level section of a page whose title is
   * an `h1` needs `h2`, or the document skips a level (axe `heading-order`, WCAG 1.3.1).
   * The level is a property of where the card sits, so only the caller can know it.
   */
  as: Heading = "h3",
  ...rest
}: HTMLAttributes<HTMLHeadingElement> & {
  as?: "h2" | "h3" | "h4";
}): JSX.Element {
  return (
    <Heading
      className={cn("text-lg font-semibold leading-none text-text", className)}
      {...rest}
    >
      {children}
    </Heading>
  );
}

export function CardContent({
  className,
  ...rest
}: HTMLAttributes<HTMLDivElement>): JSX.Element {
  return <div className={cn("p-6 pt-0", className)} {...rest} />;
}
