export type DirectoryMember = {
  id: string;
  username: string | null;
  email?: string;
  phone?: string;
  teams?: string[];
  employment_status?: string;
};

export function filterDirectory(members: DirectoryMember[], query: string): DirectoryMember[] {
  const needle = query.trim().toLowerCase();
  if (!needle) return members;
  return members.filter((member) => {
    const haystack = [member.username, member.email, member.phone, ...(member.teams ?? [])]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();
    return haystack.includes(needle);
  });
}

export function contactVisible(member: DirectoryMember): boolean {
  return member.email != null || member.phone != null;
}
