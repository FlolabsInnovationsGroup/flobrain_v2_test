export type AccessRequest = {
  id: string;
  perm_key: string;
  status: string;
  reason?: string;
};

export type AccessGrant = {
  id: string;
  perm_key: string;
  revoked_at?: string | null;
};

export function pendingRequests(rows: AccessRequest[]): AccessRequest[] {
  return rows.filter((row) => row.status === "pending" || row.status === "open");
}

export function activeGrants(rows: AccessGrant[]): AccessGrant[] {
  return rows.filter((row) => !row.revoked_at);
}

export function accessListsEmpty(requests: AccessRequest[], grants: AccessGrant[]): boolean {
  return pendingRequests(requests).length === 0 && activeGrants(grants).length === 0;
}
