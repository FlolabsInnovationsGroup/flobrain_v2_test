export function NoAccess({ label = "You do not have access" }: { label?: string }) {
  return (
    <div className="p-6 text-[color:var(--fb-v2-error)]" role="alert">
      {label}
    </div>
  );
}
