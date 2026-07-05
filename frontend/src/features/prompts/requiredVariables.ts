/**
 * Pure required-variable validation for the prompt-render form (Property 12).
 *
 * A declared variable is considered **supplied** iff the supplied map carries
 * its name with a non-empty (after trimming) string value. `missingVariables`
 * returns exactly the declared variables (de-duplicated, in declared order)
 * that were not supplied, and `canRender` is true iff none are missing — so the
 * render form blocks submission (issuing no `POST /prompts/{name}/render`) if
 * and only if at least one declared variable is unsupplied, prompting for
 * exactly the missing set (Req 12.6).
 */

/** The declared variables that have no supplied value, in declared order. */
export function missingVariables(
  declared: readonly string[],
  supplied: Readonly<Record<string, string>>,
): string[] {
  const seen = new Set<string>();
  const missing: string[] = [];
  for (const name of declared) {
    if (seen.has(name)) continue;
    seen.add(name);
    const value = supplied[name];
    if (typeof value !== "string" || value.trim().length === 0) {
      missing.push(name);
    }
  }
  return missing;
}

/** True iff every declared variable has a supplied value (render is allowed). */
export function canRender(
  declared: readonly string[],
  supplied: Readonly<Record<string, string>>,
): boolean {
  return missingVariables(declared, supplied).length === 0;
}
