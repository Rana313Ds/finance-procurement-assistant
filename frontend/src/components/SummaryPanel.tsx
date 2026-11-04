import type { SummaryState } from "../App";
import { eur, money } from "../format";

export default function SummaryPanel({ state, onRetry }: { state: SummaryState; onRetry: () => void }) {
  return (
    <div className="side-summary" aria-busy={state.status === "loading"}>
      {state.status === "loading" && <p className="side-section muted small">Loading overview…</p>}
      {state.status === "error" && (
        <div className="side-section error" role="alert">
          <p>Could not load the overview: {state.message}</p>
          <button className="btn" onClick={onRetry}>Retry</button>
        </div>
      )}
      {state.status === "ready" && <Content data={state.data} />}
    </div>
  );
}

function Stat({ label, count, value, title }: { label: string; count: number; value: number; title?: string }) {
  return (
    <li title={title}>
      <span className="stat-label">{label}<span className="count">{count}</span></span>
      <span className="v">{money(value)}</span>
    </li>
  );
}

function Content({ data }: { data: Extract<SummaryState, { status: "ready" }>["data"] }) {
  const { totals, control_flags: flags } = data;
  return (
    <>
      <section className="side-section">
        <p className="side-label">Net spend 2025</p>
        <p className="stat-big">{eur(totals.net_eur)}</p>
        <p className="muted small">
          {totals.invoice_count} invoices, {data.date_range.from} to {data.date_range.to}. Gross {eur(totals.gross_eur)},
          less {totals.credit_note_count} credit notes of {eur(totals.credit_notes_eur)}.
        </p>
      </section>

      <section className="side-section">
        <p className="side-label">By currency · EUR net</p>
        <ul className="stat-list">
          {data.by_currency.map((r) => (
            <Stat key={r.currency} label={r.currency} count={r.invoice_count} value={r.net_eur}
                  title={`${r.currency} ${money(r.native_net)} in invoice currency`} />
          ))}
        </ul>
      </section>

      <section className="side-section">
        <p className="side-label">By vendor status · EUR net</p>
        <ul className="stat-list">
          {data.by_vendor_status.map((r) => (
            <Stat key={r.vendor_status} label={r.vendor_status.replace("_", " ").toLowerCase()} count={r.invoice_count} value={r.net_eur} />
          ))}
        </ul>
      </section>

      <section className="side-section">
        <p className="side-label">Open control issues · EUR</p>
        <ul className="stat-list">
          <Stat label="Missing PO" count={flags.missing_po_count} value={flags.missing_po_eur} title="No PO at EUR 1,000 or above (§2.2)" />
          <Stat label="Missing approver" count={flags.missing_approver_count} value={flags.missing_approver_eur} title="No approver record (§3.1)" />
          <Stat label="Non-active vendor" count={flags.non_active_vendor_count} value={flags.non_active_vendor_eur} title="Vendor not ACTIVE (§4.1)" />
        </ul>
        <p className="muted small">Issues can overlap. Data version {data.provenance.data_version}.</p>
      </section>
    </>
  );
}
