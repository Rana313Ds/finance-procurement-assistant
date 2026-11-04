import { eur, money } from "../format";
import type { AskResponse, DataResult, InvoiceRow } from "../types";
import AnswerText from "./AnswerText";

const ROUTE_LABELS = {
  data: "Invoice data",
  policy: "Policy",
  both: "Invoice data + policy",
  none: "Outside available sources",
};

const GROUNDING = {
  passed: { label: "Model answer · figures checked", tone: "good" },
  template: { label: "Template answer", tone: "neutral" },
  fallback_to_template: { label: "Model answer rejected · template shown", tone: "warn" },
  declined: { label: "Declined", tone: "neutral" },
} as const;

export default function AnswerCard({ response }: { response: AskResponse }) {
  const { route, evidence, grounding } = response;
  const label = GROUNDING[grounding.status];
  const rowCount = evidence.data.reduce((n, r) => n + (r.rows?.length ?? 0), 0);

  const hasEvidence = evidence.policy.length > 0 || evidence.data.length > 0;

  return (
    <div className="answer">
      <AnswerText text={response.answer} />

      <div className="meta">
        <span className={`chip route-${route.decision}`}>{ROUTE_LABELS[route.decision]}</span>
        <span className={`chip ${label.tone}`}>{label.label}</span>
      </div>

      {response.assumptions.length > 0 && (
        <div className="assumptions">
          <p className="callout-title">Notes</p>
          <ul>{response.assumptions.map((a) => <li key={a}>{a}</li>)}</ul>
        </div>
      )}

      {grounding.status === "fallback_to_template" && (
        <details className="fold warn-box">
          <summary>Why the AI answer was rejected</summary>
          <div className="fold-body"><ul>{grounding.problems.map((p) => <li key={p}>{p}</li>)}</ul></div>
        </details>
      )}

      <details className="fold">
        <summary>Why this route</summary>
        <div className="fold-body"><p>{route.reasoning}</p></div>
      </details>

      {hasEvidence && (
        <details className="fold">
          <summary>Sources · {evidence.policy.length} policy clauses, {rowCount} invoice rows</summary>
          <div className="fold-body evidence">
            {evidence.policy.map((c) => (
              <blockquote key={c.id}>
                <strong>§{c.id} {c.section}</strong>
                <span className="muted small"> (FIN-POL-014 v3.2, line {c.line})</span>
                <div className="clause">{c.text}</div>
              </blockquote>
            ))}
            {evidence.data.map((r) => <DataEvidence key={r.id} result={r} />)}
          </div>
        </details>
      )}
      <p className="trace">
        Trace {response.trace_id.slice(0, 8)} · data {response.provenance.data_version} · prompts v{response.provenance.prompt_version}
        {response.llm.model ? ` · ${response.llm.provider}/${response.llm.model}` : " · no model"}
      </p>
    </div>
  );
}

function DataEvidence({ result }: { result: DataResult }) {
  return (
    <div className="data-evidence">
      <p className="muted small">
        <strong>{result.id}</strong>: <code>{result.tool}</code> <code>{JSON.stringify(result.parameters)}</code>
      </p>
      {result.tool === "required_approver" && (
        <p>{result.currency} {money(result.amount!)} at rate {result.fx_rate} = {eur(result.amount_eur!)}; band {result.band_eur}: <strong>{result.required_approver}</strong></p>
      )}
      {result.checks && result.checks.length > 0 && (
        <table>
          <thead><tr><th>Control</th><th>Result</th><th>Detail</th><th className="nowrap">Clause</th></tr></thead>
          <tbody>
            {result.checks.map((c) => (
              <tr key={c.check}>
                <td>{c.check}</td><td className={`status-${c.status}`}>{c.status.replace("_", " ")}</td>
                <td>{c.detail}</td><td>§{c.clause}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {result.groups && (
        <table>
          <thead><tr><th>Group</th><th className="num">Invoices</th><th className="num">EUR net</th><th className="num">Credit notes</th></tr></thead>
          <tbody>
            {result.groups.map((g) => (
              <tr key={g.key}><td>{g.key}</td><td className="num">{g.invoice_count}</td><td className="num">{money(g.net_eur)}</td><td className="num">{money(g.credit_notes_eur)}</td></tr>
            ))}
          </tbody>
        </table>
      )}
      {result.totals && (
        <p className="small">
          All matching invoices: {result.totals.invoice_count}, net {eur(result.totals.net_eur)}.
          {" "}Native: {Object.entries(result.totals.native_net).map(([c, v]) => `${c} ${money(v)}`).join(", ") || "none"}.
        </p>
      )}
      {result.rows && result.rows.length > 0 && <Rows rows={result.rows} scope={result.rows_scope} />}
    </div>
  );
}

function Rows({ rows, scope }: { rows: InvoiceRow[]; scope?: string }) {
  return (
    <details open={rows.length <= 5}>
      <summary>Source invoices: {rows.length} {rows.length === 1 ? "row" : "rows"}{scope ? ` (${scope})` : ""}</summary>
      <div className="table-scroll">
        <table>
          <thead>
            <tr><th>Invoice</th><th>Date</th><th>Vendor</th><th>Status</th><th className="num">Amount</th><th>Cur</th><th className="num">Rate</th><th className="num">EUR</th><th>PO</th><th>Approver</th><th className="num">CSV line</th></tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.invoice_number}>
                <td>{r.invoice_number}</td><td>{r.invoice_date}</td><td>{r.vendor_name}</td>
                <td className={r.vendor_status === "ACTIVE" ? "" : "flag"}>{r.vendor_status}</td>
                <td className="num">{money(r.amount)}</td><td>{r.currency}</td><td className="num">{r.fx_rate}</td>
                <td className="num">{money(r.amount_eur)}</td>
                <td className={r.po_number ? "" : "flag"}>{r.po_number || "missing"}</td>
                <td className={r.approved_by ? "" : "flag"}>{r.approved_by || "missing"}</td>
                <td className="num">{r.source_line}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}
