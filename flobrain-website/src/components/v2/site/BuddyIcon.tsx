import type { Buddy } from "./content";

/** A buddy's gradient tile with its icon. Server-safe, so pages can pass buddy data straight in. */
export function BuddyIcon({ buddy, size = 40, radius = 12 }: { buddy: Buddy; size?: number; radius?: number }) {
  const Icon = buddy.icon;
  return (
    <span
      aria-hidden
      style={{
        flex: "none",
        display: "grid",
        placeItems: "center",
        width: size,
        height: size,
        borderRadius: radius,
        background: buddy.gradient,
        boxShadow: "inset 0 1px 0 rgba(255,255,255,.25), 0 6px 16px -6px rgba(0,0,0,.6)",
      }}
    >
      <Icon size={Math.round(size * 0.47)} color="#fff" strokeWidth={2} />
    </span>
  );
}
