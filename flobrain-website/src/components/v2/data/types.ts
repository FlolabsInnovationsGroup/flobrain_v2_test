export type ColumnType = "integer" | "real" | "boolean" | "date" | "datetime" | "text";
export type Column = { name: string; label: string; type: ColumnType };
export type Table = { name: string; label: string; columns: Column[]; sample_rows: unknown[][]; row_count: number | null };

export type Dataset = {
  id: string;
  name: string;
  description: string;
  kind: "upload" | "sheet" | "postgres";
  status: "ready" | "refreshing" | "error";
  last_error: string;
  visibility: "org" | "team" | "owner";
  team: string | null;
  owner: string | null;
  tables: Table[];
  row_count: number;
  source_name: string;
  sheet_url: string;
  refresh_every_hours: number;
  next_refresh_at: string | null;
  last_refreshed_at: string | null;
  connection: string | null;
  created_at: string;
  can_manage?: boolean;
  cards?: Card[];
};

export type ChartSpec = { type: "bar" | "line" | "table" | "number"; x: string | null; y: string[]; series: string | null };
export type Result = { columns: string[]; rows: unknown[][]; truncated?: boolean };

export type AskResult = Result & {
  dataset: string;
  question: string;
  sql: string;
  chart: ChartSpec;
  chart_fixed: boolean;
  answer: string;
  row_count?: number;
  ms?: number;
};

export type Card = {
  id: string;
  dataset: string;
  dataset_name: string;
  title: string;
  question: string;
  sql: string;
  chart: ChartSpec;
  answer: string;
  result: Result;
  last_run_at: string | null;
  created_by: string | null;
  created_at: string;
};

export type ReportResult = { card: string; title: string; headline: string; error: string };

export type Report = {
  id: string;
  name: string;
  cards: string[];
  recipients: string[];
  cadence: "weekly" | "monthly";
  weekday: number;
  day_of_month: number;
  hour: number;
  room: string | null;
  enabled: boolean;
  next_run_at: string | null;
  last_run_at: string | null;
  last_status: string;
  last_results: ReportResult[];
  created_by: string;
};

export type Meta = {
  can_manage: boolean;
  is_admin: boolean;
  allow_private_hosts: boolean;
  postgres_available: boolean;
  max_upload_mb: number;
  max_rows: number;
  query_max_rows: number;
  query_seconds: number;
};
