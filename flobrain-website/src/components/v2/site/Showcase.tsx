"use client";

import { Focus, Layers, LayoutGrid, Send } from "lucide-react";
import Image from "next/image";
import { useRef, useState } from "react";

import { BuddyIcon } from "./BuddyIcon";
import { BUDDIES } from "./content";

export { BuddyIcon };

/** Roving-focus keyboard support for a horizontal or grid set of tabs. */
function useArrows(count: number, select: (i: number) => void) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const onKeyDown = (i: number) => (event: React.KeyboardEvent) => {
    const step = event.key === "ArrowRight" || event.key === "ArrowDown" ? 1 : event.key === "ArrowLeft" || event.key === "ArrowUp" ? -1 : 0;
    if (!step) return;
    event.preventDefault();
    const next = (i + step + count) % count;
    select(next);
    refs.current[next]?.focus();
  };
  return { refs, onKeyDown };
}

const MODES = [
  { key: "default", label: "Default", icon: LayoutGrid, src: "/v2/shots/cockpit.webp", alt: "The cockpit with rooms on the left, a buddy answering with sources and an approval card in the middle, and the impact score, tasks and buddies on the right." },
  { key: "focus", label: "Focus", icon: Focus, src: "/v2/shots/cockpit-focus.webp", alt: "Focus mode: only the conversation with the buddy, sidebars hidden and notifications held." },
  { key: "custom", label: "Custom", icon: Layers, src: "/v2/shots/cockpit-custom.webp", alt: "A custom layout pinned to the task board, without the right column." },
];

export function ModesShowcase() {
  const [active, setActive] = useState(0);
  const { refs, onKeyDown } = useArrows(MODES.length, setActive);
  const mode = MODES[active];
  return (
    <div style={{ marginTop: 44 }}>
      <div className="tabbar" role="tablist" aria-label="Cockpit layouts">
        {MODES.map((m, i) => {
          const Icon = m.icon;
          return (
            <button
              key={m.key}
              ref={(el) => {
                refs.current[i] = el;
              }}
              type="button"
              role="tab"
              id={`mode-tab-${m.key}`}
              aria-selected={i === active}
              aria-controls="mode-panel"
              tabIndex={i === active ? 0 : -1}
              onClick={() => setActive(i)}
              onKeyDown={onKeyDown(i)}
            >
              <Icon size={16} aria-hidden />
              {m.label}
            </button>
          );
        })}
      </div>
      <div id="mode-panel" role="tabpanel" aria-labelledby={`mode-tab-${mode.key}`} style={{ marginTop: 20 }}>
        <div key={mode.key} className="frame hide-sm fadein">
          <Image src={mode.src} alt={mode.alt} width={2880} height={1800} sizes="(max-width: 1240px) 100vw, 1200px" />
        </div>
        <div className="phone">
          <Image src="/v2/shots/mobile-room.webp" alt="The Launch room on a phone, with a buddy reply and a translated Arabic message." width={780} height={1600} sizes="300px" />
        </div>
      </div>
    </div>
  );
}

export function Crew() {
  const [active, setActive] = useState(5);
  const { refs, onKeyDown } = useArrows(BUDDIES.length, setActive);
  const buddy = BUDDIES[active];
  return (
    <div className="wrapc" style={{ marginTop: 44, display: "grid", gridTemplateColumns: "minmax(0,.9fr) minmax(0,1.1fr)", gap: 16 }}>
      <div className="crew-list" role="tablist" aria-label="Buddies">
        {BUDDIES.map((b, i) => (
          <button
            key={b.name}
            ref={(el) => {
              refs.current[i] = el;
            }}
            type="button"
            role="tab"
            aria-selected={i === active}
            aria-controls="crew-panel"
            tabIndex={i === active ? 0 : -1}
            onClick={() => setActive(i)}
            onKeyDown={onKeyDown(i)}
          >
            <BuddyIcon buddy={b} />
            <span style={{ minWidth: 0 }}>
              <b style={{ display: "block", font: "600 15px var(--fd)" }}>{b.name} buddy</b>
              <span className="role" style={{ font: "400 13px var(--fb)", color: "var(--tx3)" }}>
                {b.role}
              </span>
            </span>
          </button>
        ))}
      </div>
      <div id="crew-panel" role="tabpanel" aria-live="polite" className="card" style={{ padding: "clamp(18px,3vw,32px)", minHeight: 360, display: "flex", flexDirection: "column" }}>
        <p className="k" style={{ margin: "0 0 22px" }}>
          {buddy.name.toUpperCase()} BUDDY
        </p>
        <div key={buddy.name} className="fadein" style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <p className="me" style={{ margin: 0 }}>
            {buddy.ask}
          </p>
          <div className="msg">
            <BuddyIcon buddy={buddy} size={32} radius={10} />
            <p className="bub" style={{ margin: 0 }}>
              {buddy.answer}
            </p>
          </div>
        </div>
        <div className="comp" aria-hidden style={{ marginTop: "auto" }}>
          Ask anything, or @mention a buddy
          <span className="sb" style={{ width: 34, padding: 0, marginLeft: "auto", background: "var(--vi)", color: "#fff" }}>
            <Send size={15} />
          </span>
        </div>
      </div>
    </div>
  );
}
