/**
 * Design-system primitive barrel. Prefer importing individual primitives
 * directly (e.g. `import { Button } from "components/ui/Button"`) for the
 * leanest bundles; this barrel is a convenience and remains tree-shakeable
 * under the ESM build.
 */
export { Button } from "./Button";
export type { ButtonProps, ButtonVariant, ButtonSize } from "./Button";
export { Input } from "./Input";
export type { InputProps } from "./Input";
export { Card, CardHeader, CardTitle, CardContent } from "./Card";
export { Badge } from "./Badge";
export type { BadgeTone } from "./Badge";
export { Skeleton } from "./Skeleton";
export { PageHeader } from "./PageHeader";
export { StatCard } from "./StatCard";
export type { StatTone } from "./StatCard";
export { Kbd } from "./Kbd";
export {
  Dialog,
  DialogTrigger,
  DialogClose,
  DialogContent,
} from "./Dialog";
export { Tabs, TabsList, TabsTrigger, TabsContent } from "./Tabs";
export { Tooltip, TooltipProvider } from "./Tooltip";
export {
  Popover,
  PopoverTrigger,
  PopoverAnchor,
  PopoverContent,
} from "./Popover";
export {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
} from "./DropdownMenu";
export {
  Toast,
  ToastViewport,
  ToastProviderPrimitive,
} from "./Toast";
export type { ToastTone } from "./Toast";
