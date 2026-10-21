import Image from "next/image";

/** The FloLabs hand in its violet to blue gradient. Decorative unless a label is given. */
export function BrandMark({ size = 26, label, className }: { size?: number; label?: string; className?: string }) {
  return (
    <Image
      src={size > 48 ? "/v2/flobrain-mark@2x.png" : "/v2/flobrain-mark.png"}
      alt={label ?? ""}
      aria-hidden={label ? undefined : true}
      width={size}
      height={size}
      className={className}
      priority={size <= 32}
    />
  );
}

/** "FloBrain" with "Brain" lit in the aurora, as in the cockpit top bar. */
export function Wordmark({ className }: { className?: string }) {
  return (
    <span className={className} style={{ fontWeight: 600, letterSpacing: "-0.03em" }}>
      Flo<span className="v2-aurora-text">Brain</span>
    </span>
  );
}
