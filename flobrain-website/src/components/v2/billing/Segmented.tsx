"use client";

import { useRef } from "react";

export type SegmentOption<T extends string> = { value: T; label: React.ReactNode; name?: string };

/**
 * A radiogroup of buttons (Monthly | Yearly, Per person | Per workspace). Arrow keys, Home and End
 * move and select; only the checked option is in the tab order. Unstyled: pass the container class
 * (the V2 site uses `tabbar`, which styles `[aria-checked="true"]`).
 */
export function Segmented<T extends string>({
  label,
  value,
  options,
  onChange,
  className,
  buttonClassName,
}: {
  label: string;
  value: T;
  options: SegmentOption<T>[];
  onChange: (value: T) => void;
  className?: string;
  buttonClassName?: (checked: boolean) => string;
}) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const index = Math.max(0, options.findIndex((o) => o.value === value));

  function move(next: number) {
    const i = (next + options.length) % options.length;
    onChange(options[i].value);
    refs.current[i]?.focus();
  }

  function onKeyDown(e: React.KeyboardEvent) {
    const rtl = typeof document !== "undefined" && document.documentElement.dir === "rtl";
    const forward = rtl ? "ArrowLeft" : "ArrowRight";
    const back = rtl ? "ArrowRight" : "ArrowLeft";
    if (e.key === forward || e.key === "ArrowDown") move(index + 1);
    else if (e.key === back || e.key === "ArrowUp") move(index - 1);
    else if (e.key === "Home") move(0);
    else if (e.key === "End") move(options.length - 1);
    else return;
    e.preventDefault();
  }

  return (
    <div className={className} role="radiogroup" aria-label={label} onKeyDown={onKeyDown}>
      {options.map((o, i) => {
        const checked = o.value === value;
        return (
          <button
            key={o.value}
            ref={(el) => {
              refs.current[i] = el;
            }}
            type="button"
            role="radio"
            aria-checked={checked}
            aria-label={o.name}
            tabIndex={checked ? 0 : -1}
            className={buttonClassName?.(checked)}
            onClick={() => onChange(o.value)}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}
