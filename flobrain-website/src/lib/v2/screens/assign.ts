export type AssignActorRole = "member" | "lead" | "admin" | "owner";

export function canAssignOther(role: AssignActorRole, sameTeam: boolean): boolean {
  if (role === "member") return false;
  if (role === "lead") return sameTeam;
  return true;
}

export function assignFailureStatus(role: AssignActorRole, sameTeam: boolean, assigneeActive: boolean): number {
  if (!assigneeActive) return 404;
  if (role === "member") return 403;
  if (role === "lead" && !sameTeam) return 404;
  return 200;
}
