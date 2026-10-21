export type Source = "slack" | "notion_zip" | "notion_api" | "drive_api" | "files";
export type Status = "analyzing" | "ready" | "queued" | "running" | "done" | "failed" | "cancelled" | "undoing" | "undone";

export type SlackChannel = {
  id: string;
  name: string;
  kind: "public" | "private" | "dm" | "group_dm";
  archived: boolean;
  messages: number;
  threads: number;
  first: string;
  last: string;
  members: number;
  matched: number;
  suggested_team: string;
};

export type SlackPerson = {
  slack_id: string;
  name: string;
  matched: boolean;
  member_id: string;
  member_name: string;
  shown_as: string;
};

export type DocItem = {
  ref: string;
  name: string;
  kind: string;
  size: number;
  supported: boolean;
  reason: string;
  notion_id: string;
};

export type Preview = {
  channels?: SlackChannel[];
  people?: SlackPerson[];
  items?: DocItem[];
  has_private?: boolean;
  has_dms?: boolean;
  totals?: Record<string, number | string>;
};

export type ChannelChoice = { target: "team" | "new_team" | "private" | "skip"; team_id?: string };

export type SlackMapping = {
  channels: Record<string, ChannelChoice>;
  include_private: boolean;
  include_dms: boolean;
  include_bots: boolean;
};

export type Run = {
  id: string;
  source: Source;
  label: string;
  status: Status;
  error: string;
  progress: { done?: number; total?: number; current?: string };
  counts: Record<string, number>;
  cancel_requested: boolean;
  is_demo: boolean;
  files: { name: string; size: number }[];
  created_by: string;
  created_at: string;
  started_at: string;
  finished_at: string;
  undone_at: string;
  can_undo: boolean;
  can_resume: boolean;
  preview?: Preview;
  mapping?: Record<string, unknown>;
};

export type Place = { id: string; name: string; kind?: string };

export type Meta = {
  max_upload_mb: number;
  max_files_per_upload: number;
  max_file_mb: number;
  drive_max_file_mb: number;
  pdf_supported: boolean;
  docx_supported: boolean;
  file_types: string[];
  is_admin: boolean;
  demo: boolean;
  rooms: Place[];
  teams: Place[];
  notion: { id: string; label: string; simulated: boolean }[];
  drive: { status: "ready" | "needs_scope" | "not_connected"; message: string; simulated: boolean };
  active: Run | null;
};

export type NotionPage = { id: string; type: "page" | "database"; title: string; url: string; last_edited: string };

export type DriveFile = {
  id: string;
  name: string;
  kind: string;
  size: number;
  modified: string;
  url: string;
  too_big: boolean;
  supported: boolean;
};
