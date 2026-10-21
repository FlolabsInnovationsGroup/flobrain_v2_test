import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import * as React from "react";

import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center rounded-[length:var(--fb-v2-radius)] px-3 py-2 text-sm font-medium",
  {
    variants: {
      variant: {
        default: "bg-[color:var(--fb-v2-accent)] text-white",
        ghost: "bg-transparent text-[color:var(--fb-v2-text)]",
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
