/** Notification sounds, synthesised in the browser so nothing is downloaded. */
export const SOUNDS: Record<string, { label: string; notes: number[] }> = {
  none: { label: "None", notes: [] },
  chime: { label: "Chime", notes: [880, 1320] },
  pop: { label: "Pop", notes: [660] },
  ping: { label: "Ping", notes: [1568] },
  bell: { label: "Bell", notes: [523, 659, 784] },
  soft: { label: "Soft", notes: [392, 523] },
  knock: { label: "Knock", notes: [180, 180] },
};

export function play(key: string) {
  const sound = SOUNDS[key];
  if (!sound || !sound.notes.length || typeof window === "undefined") return;
  const Ctx = window.AudioContext || (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
  if (!Ctx) return;
  const ctx = new Ctx();
  sound.notes.forEach((freq, i) => {
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.frequency.value = freq;
    const start = ctx.currentTime + i * 0.12;
    gain.gain.setValueAtTime(0.0001, start);
    gain.gain.exponentialRampToValueAtTime(0.2, start + 0.01);
    gain.gain.exponentialRampToValueAtTime(0.0001, start + 0.25);
    osc.connect(gain).connect(ctx.destination);
    osc.start(start);
    osc.stop(start + 0.3);
  });
}
