export function Empty({ label = "No data yet" }: { label?: string }) {
  return (
    <div className="p-6 text-[color:var(--fb-v2-text-muted)]">{label}</div>
  );
}
