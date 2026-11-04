import { Fragment, ReactNode } from "react";

/**
 * Lays out the plain-text answer as readable blocks. The text itself is unchanged: this only
 * recognises the template's line shapes (rankings, invoice lines, control checks, clauses).
 */
const RANK = /^(\d+)\. (.+): (EUR -?[\d,]+\.\d{2}) \((\d+) invoices?\)$/;
const INVOICE = /^- (INV-\d+), (\d{4}-\d{2}-\d{2}), (.+?): (EUR -?[\d,]+\.\d{2})(?: \(([A-Z]{3} -?[\d,]+\.\d{2})\))?(?: \[(.+)\])?$/;
const CHECK = /^- (.+?) \[(pass|fail|cannot_verify)\]: (.+)$/;
const CLAUSE = /^§(\d+(?:\.\d+)?)([^:]*): ([\s\S]+)$/;
const AMOUNT = /(EUR -?[\d,]+\.\d{2})/g;

export function emphasise(text: string): ReactNode {
  return text.split(AMOUNT).map((part, i) =>
    i % 2 ? <strong key={i} className="figure">{part}</strong> : <Fragment key={i}>{part}</Fragment>);
}

export default function AnswerText({ text }: { text: string }) {
  return <div className="answer-text">{text.split(/\n{2,}/).map((block, i) => <Block key={i} block={block} />)}</div>;
}

function Block({ block }: { block: string }) {
  const lines = block.split("\n");
  const clause = lines.length === 1 && CLAUSE.exec(block);
  if (clause) {
    return (
      <div className="clause-block">
        <span className="clause-id">§{clause[1]}</span>
        <p>{clause[2].trim() && <strong>{clause[2].trim()}: </strong>}{clause[3]}</p>
      </div>
    );
  }

  const [first, ...rest] = lines;
  const lead = rest.length && !isItem(first) ? first : null;
  const items = lead ? rest : lines;
  if (!items.every(isItem)) {
    return <>{lines.map((l, i) => <p key={i}>{emphasise(l)}</p>)}</>;
  }
  return (
    <>
      {lead && <p className="lead">{emphasise(lead)}</p>}
      {RANK.test(items[0]) ? <Ranking items={items} /> :
       INVOICE.test(items[0]) ? <Invoices items={items} /> :
       CHECK.test(items[0]) ? <Checks items={items} /> :
       <ul className="plain-list">{items.map((l, i) => <li key={i}>{emphasise(l.replace(/^- /, ""))}</li>)}</ul>}
    </>
  );
}

const isItem = (line: string) => /^(- |\d+\. )/.test(line);

function Ranking({ items }: { items: string[] }) {
  return (
    <div className="table-scroll">
      <table className="answer-table">
        <thead><tr><th className="rank">#</th><th>Name</th><th className="num">Net spend</th><th className="num">Invoices</th></tr></thead>
        <tbody>
          {items.map((line) => {
            const m = RANK.exec(line);
            return m ? (
              <tr key={line}><td className="rank">{m[1]}</td><td>{m[2]}</td><td className="num strong">{m[3]}</td><td className="num">{m[4]}</td></tr>
            ) : <tr key={line}><td colSpan={4}>{line}</td></tr>;
          })}
        </tbody>
      </table>
    </div>
  );
}

function Invoices({ items }: { items: string[] }) {
  return (
    <div className="table-scroll">
      <table className="answer-table">
        <thead><tr><th>Invoice</th><th>Date</th><th>Vendor</th><th className="num">Amount</th><th>Flags</th></tr></thead>
        <tbody>
          {items.map((line) => {
            const m = INVOICE.exec(line);
            if (!m) return <tr key={line}><td colSpan={5}>{line}</td></tr>;
            const [, id, date, vendor, amount, native, flags] = m;
            return (
              <tr key={line}>
                <td className="mono">{id}</td><td className="nowrap">{date}</td><td>{vendor}</td>
                <td className="num"><span className="strong">{amount}</span>{native && <span className="sub">{native}</span>}</td>
                <td>{flags?.split(", ").map((f) => <span key={f} className="tag">{f.replace("_", " ")}</span>)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function Checks({ items }: { items: string[] }) {
  return (
    <ul className="checks">
      {items.map((line) => {
        const m = CHECK.exec(line);
        if (!m) return <li key={line}>{line}</li>;
        return (
          <li key={line}>
            <span className={`dot ${m[2]}`} aria-hidden />
            <div><strong>{m[1]}</strong> <span className={`status status-${m[2]}`}>{m[2].replace("_", " ")}</span>
              <div className="check-detail">{m[3]}</div></div>
          </li>
        );
      })}
    </ul>
  );
}
