import type { DirectoryMember } from "./directory";

export function canViewMemberProfile(
  member: DirectoryMember | null,
  viewerCanManage: boolean,
): boolean {
  if (!member) return false;
  if (member.employment_status === "pending" && !viewerCanManage) return false;
  return true;
}

export function profileHeadline(member: DirectoryMember): string {
  return member.username || member.email || member.id;
}
