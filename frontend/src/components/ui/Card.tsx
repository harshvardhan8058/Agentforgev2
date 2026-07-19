/**
 * `Card`: a token-styled surface container with optional raised elevation.
 * Composed of `Card`, `CardHeader`, `CardTitle`, and `CardContent`.
 */
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
  ...rest
}: HTMLAttributes<HTMLHeadingElement>): JSX.Element {
  return (
    <h3
      className={cn("text-lg font-semibold leading-none text-text", className)}
      {...rest}
    />
  );
}

export function CardContent({
  className,
  ...rest
}: HTMLAttributes<HTMLDivElement>): JSX.Element {
  return <div className={cn("p-6 pt-0", className)} {...rest} />;
}
