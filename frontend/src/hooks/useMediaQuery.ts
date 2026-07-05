/**
 * `useMediaQuery`: subscribe to a CSS media query and re-render on changes.
 *
 * Drives the app shell's responsive adaptation (persistent sidebar vs. mobile
 * drawer) from a single reactive source. SSR/test-safe: returns `false` when
 * `matchMedia` is unavailable, and reads the live value on mount.
 */
import { useEffect, useState } from "react";

function evaluate(query: string): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return false;
  }
  return window.matchMedia(query).matches;
}

export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState<boolean>(() => evaluate(query));

  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
      return;
    }
    const media = window.matchMedia(query);
    const onChange = (): void => setMatches(media.matches);
    onChange();
    media.addEventListener?.("change", onChange);
    return () => media.removeEventListener?.("change", onChange);
  }, [query]);

  return matches;
}
