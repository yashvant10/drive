import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";
import type { ComponentProps } from "react";

const buttonVariants = cva("button", {
  variants: {
    variant: {default: "", outline: "secondary"},
    size: {default: "", compact: "compact"},
  },
  defaultVariants: {variant:"default",size:"default"},
});

type ButtonProps = ComponentProps<"button"> & VariantProps<typeof buttonVariants> & {asChild?:boolean};

export function Button({className,variant,size,asChild,...props}: ButtonProps) {
  const Component = asChild ? Slot : "button";
  return <Component data-slot="button" className={cn(buttonVariants({variant,size}),className)} {...props} />;
}
