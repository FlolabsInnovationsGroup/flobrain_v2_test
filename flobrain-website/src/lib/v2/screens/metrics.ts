export function impactScoreLabel(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "Not configured";
  return String(value);
}
