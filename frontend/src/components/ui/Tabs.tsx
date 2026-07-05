/**
 * `Tabs`: token-styled tabs over Radix Tabs (roving focus + arrow-key
 * navigation + correct ARIA inherited from Radix).
 */
import * as RadixTabs from "@radix-ui/react-tabs";
import { forwardRef, type ComponentPropsWithoutRef } from "react";

import { cn } from "../../lib/cn";

export const Tabs = RadixTabs.Root;

export const TabsList = forwardRef<
  HTMLDivElement,
  ComponentPropsWithoutRef<typeof RadixTabs.List>
>(function TabsList({ className, ...rest }, ref) {
  return (
    <RadixTabs.List
      ref={ref}
      className={cn(
        "inline-flex items-center gap-1 rounded-lg border border-border bg-surface p-1",
        className,
      )}
      {...rest}
    />
  );
});

export const TabsTrigger = forwardRef<
  HTMLButtonElement,
  ComponentPropsWithoutRef<typeof RadixTabs.Trigger>
>(function TabsTrigger({ className, ...rest }, ref) {
  return (
    <RadixTabs.Trigger
      ref={ref}
      className={cn(
        "rounded-md px-3 py-1.5 text-sm font-medium text-text-muted transition-colors",
        "hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus-ring",
        "data-[state=active]:bg-surface-raised data-[state=active]:text-text",
        className,
      )}
      {...rest}
    />
  );
});

export const TabsContent = forwardRef<
  HTMLDivElement,
  ComponentPropsWithoutRef<typeof RadixTabs.Content>
>(function TabsContent({ className, ...rest }, ref) {
  return (
    <RadixTabs.Content
      ref={ref}
      className={cn(
        "mt-3 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus-ring",
        className,
      )}
      {...rest}
    />
  );
});
