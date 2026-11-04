// Mirrors the backend's response contract.
export interface LlmMode { is_stub: boolean; provider: string; model: string | null }
export interface FxInfo { mode: string; policy_compliant: boolean; note: string }

export interface Totals {
  invoice_count: number;
  net_eur: number;
  gross_eur: number;
  credit_notes_eur: number;
  credit_note_count: number;
  native_net: Record<string, number>;
}

export interface ControlFlags {
  missing_po_count: number;
  missing_po_eur: number;
  missing_approver_count: number;
  missing_approver_eur: number;
  non_active_vendor_count: number;
  non_active_vendor_eur: number;
}

export interface Summary {
  totals: Totals;
  by_currency: { currency: string; invoice_count: number; native_net: number; net_eur: number }[];
  by_vendor_status: { vendor_status: string; invoice_count: number; net_eur: number }[];
  control_flags: ControlFlags;
  date_range: { from: string; to: string };
  fx: FxInfo;
  llm: LlmMode;
  provenance: { data_version: string; source_rows: number };
}

export interface InvoiceRow {
  invoice_number: string;
  invoice_date: string;
  vendor_name: string;
  country: string;
  vendor_status: string;
  description: string;
  amount: number;
  currency: string;
  fx_rate: number;
  amount_eur: number;
  cost_center: string;
  po_number: string;
  approved_by: string;
  source_line: number;
}

export interface Group { key: string; invoice_count: number; net_eur: number; credit_notes_eur: number }
export interface ControlCheck { check: string; status: "pass" | "fail" | "cannot_verify"; clause: string; detail: string }

export interface DataResult {
  id: string;
  tool: "query_invoices" | "check_invoice" | "required_approver";
  parameters: Record<string, unknown>;
  rows?: InvoiceRow[];
  rows_scope?: string;
  groups?: Group[] | null;
  totals?: Totals;
  checks?: ControlCheck[];
  found?: boolean;
  amount?: number;
  currency?: string;
  fx_rate?: number;
  amount_eur?: number;
  band_eur?: string;
  required_approver?: string;
}

export interface PolicyClause { id: string; section: string; text: string; line: number }

export interface AskResponse {
  trace_id: string;
  answer: string;
  answer_source: "llm" | "template";
  route: { decision: "data" | "policy" | "both" | "none"; reasoning: string };
  evidence: { policy: PolicyClause[]; data: DataResult[] };
  assumptions: string[];
  grounding: { status: "passed" | "template" | "fallback_to_template" | "declined"; problems: string[] };
  llm: LlmMode;
  fx: FxInfo;
  provenance: { data_version: string; prompt_version: string };
}
