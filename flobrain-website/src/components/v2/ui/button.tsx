import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import * as React from "react";

import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center rounded-[length:var(--fb-v2-radius)] px-3 py-2 text-sm font-medium",
  {
    variants: {
      variant: {
        default: "bg-[color:var(--fb-v2-accent)] text-white hover:bg-[color:var(--fb-v2-accent-strong)] disabled:opacity-50",
        ghost: "bg-transparent text-[color:var(--fb-v2-text)] hover:bg-[color:var(--fb-v2-border)] disabled:opacity-50",
        outline: "bg-transparent text-[color:var(--fb-v2-text)] ring-1 ring-inset ring-[color:var(--fb-v2-border)] hover:bg-[color:var(--fb-v2-border)] disabled:opacity-50",
        waiting: "bg-[color:var(--fb-v2-waiting)] text-black hover:brightness-110 disabled:opacity-50",
        danger: "bg-transparent text-[color:var(--fb-v2-error)] ring-1 ring-inset ring-[color:var(--fb-v2-error)] hover:bg-[color:var(--fb-v2-error)] hover:text-black disabled:opacity-50",
      },
    },
    defaultVariants: { variant: "default" },
  }
);

export function Button({
  className,
  variant,
  asChild = false,
  ...props
}: React.ComponentProps<"button"> &
  VariantProps<typeof buttonVariants> & { asChild?: boolean }) {
  const Comp = asChild ? Slot : "button";
  return <Comp className={cn(buttonVariants({ variant, className }))} {...props} />;
}
