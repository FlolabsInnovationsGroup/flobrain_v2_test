export function Loading({ label = "Loading" }: { label?: string }) {
  return (
    <div role="status" className="p-6 text-[color:var(--fb-v2-text-muted)]">
      {label}…
    </div>
  );
}
