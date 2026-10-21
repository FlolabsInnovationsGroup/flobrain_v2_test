import { cn } from "@/lib/utils";

/**
 * The one brand signature: a planet horizon lit in the logo's spectrum (magenta, violet, cyan).
 * Purely decorative. Place inside a ``position: relative; overflow: hidden`` parent; ``top`` sets
 * where the rim sits.
 */
export function AuroraHorizon({ top = "70%", size = 2600, className }: { top?: string; size?: number; className?: string }) {
  return (
    <div aria-hidden className={cn("pointer-events-none absolute inset-0 overflow-hidden", className)}>
      <div
        className="absolute inset-0 opacity-70"
        style={{
          backgroundImage:
            "radial-gradient(1px 1px at 20% 30%,#ffffff88,transparent),radial-gradient(1px 1px at 70% 20%,#ffffff66,transparent),radial-gradient(1.4px 1.4px at 85% 60%,#c9c0ff99,transparent),radial-gradient(1px 1px at 35% 75%,#ffffff55,transparent),radial-gradient(1px 1px at 55% 45%,#ffffff44,transparent),radial-gradient(1.2px 1.2px at 12% 62%,#7fe3ff88,transparent),radial-gradient(1px 1px at 92% 35%,#ffffff66,transparent)",
          backgroundSize: "520px 520px",
        }}
      />
      <div className="absolute left-1/2 rounded-full" style={{ top, width: size, height: size, marginLeft: -size / 2 }}>
        <div
          className="absolute rounded-full opacity-55 blur-[80px]"
          style={{ inset: -60, background: "conic-gradient(from 180deg,#cc34ff,#7c6bff,#00d4ff,#7c6bff,#cc34ff)" }}
        />
        <div className="absolute inset-0 rounded-full" style={{ background: "linear-gradient(90deg,#cc34ff,#7c6bff 50%,#00d4ff)" }} />
        <div
          className="absolute rounded-full"
          style={{
            inset: 2,
            background:
              "radial-gradient(60% 6% at 50% 0%,rgba(169,155,255,.35),transparent 70%),linear-gradient(180deg,#0d0b1a 0%,#08070f 12%)",
          }}
        />
      </div>
    </div>
  );
}
