/**
 * `cn`: the class-merge utility used across the design-system primitives.
 *
 * Combines `clsx` (conditional class composition) with `tailwind-merge`
 * (deduping/last-wins for conflicting Tailwind utilities) so component variants
 * and caller overrides compose predictably.
 */
import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
