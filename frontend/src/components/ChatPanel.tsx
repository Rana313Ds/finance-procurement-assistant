import { FormEvent, useEffect, useLayoutEffect, useRef, useState } from "react";
import { ApiError, ask } from "../api";
import type { AskResponse } from "../types";
import AnswerCard from "./AnswerCard";
import { LogoIcon, SendIcon } from "./icons";

type Turn = { id: number; question: string } & (
  | { status: "pending" }
  | { status: "done"; response: AskResponse }
  | { status: "error"; message: string; retryable: boolean }
);

const EXAMPLES = [
  "What are our top 5 vendors by total spend in 2025?",
  "What is our total spend with vendors based in Spain?",
  "Who is allowed to approve an invoice of EUR 60,000?",
  "Which invoices from on hold vendors need escalation?",
  "Can INV-20005 be paid?",
];
const MAX_LENGTH = 1000;

export default function ChatPanel() {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState("");
  const nextId = useRef(1);
  const lastRef = useRef<HTMLElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const busy = turns.some((t) => t.status === "pending");
  const empty = turns.length === 0;

  // A new question scrolls to the top of the view, so its answer fills the space below it.
  useEffect(() => {
    lastRef.current?.scrollIntoView?.({ behavior: "smooth", block: "start" });
  }, [turns.length]);

  // Grow the textarea with its content, up to the CSS max-height.
  useLayoutEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  }, [draft]);

  const update = (id: number, next: Turn) => setTurns((all) => all.map((t) => (t.id === id ? next : t)));

  const run = async (id: number, question: string) => {
    update(id, { id, question, status: "pending" });
    try {
      update(id, { id, question, status: "done", response: await ask(question) });
    } catch (err) {
      const e = err as ApiError;
      update(id, { id, question, status: "error", message: e.message, retryable: e.retryable });
    }
  };

  const submit = (question: string) => {
    const text = question.trim();
    if (!text || busy) return;
    const id = nextId.current++;
    setTurns((all) => [...all, { id, question: text, status: "pending" }]);
    setDraft("");
    void run(id, text);
  };

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    submit(draft);
  };

  return (
    <div className={`chat ${empty ? "empty" : ""}`}>
      <div className="thread" aria-live="polite">
        {empty ? (
          <div className="hero">
            <h1>What would you like to know?</h1>
            <p className="muted">Ask about 2025 invoices and the procurement policy.</p>
          </div>
        ) : (
          turns.map((turn, i) => (
            <article key={turn.id} className="turn" ref={i === turns.length - 1 ? lastRef : undefined}>
              <div className="msg user"><div className="bubble">{turn.question}</div></div>
              <div className="msg assistant">
                <div className="avatar"><LogoIcon size={16} /></div>
                <div className="content">
                  {turn.status === "pending" && (
                    <div className="typing" role="status" aria-label="Checking the data and policy">
                      <span /><span /><span />
                    </div>
                  )}
                  {turn.status === "error" && (
                    <div className="error" role="alert">
                      <p>{turn.message}</p>
                      {turn.retryable && (
                        <button className="btn" disabled={busy} onClick={() => void run(turn.id, turn.question)}>Retry</button>
                      )}
                    </div>
                  )}
                  {turn.status === "done" && <AnswerCard response={turn.response} />}
                </div>
              </div>
            </article>
          ))
        )}
      </div>

      <div className="composer-wrap">
        <form onSubmit={onSubmit} className="composer">
          <label htmlFor="question" className="sr-only">Your question</label>
          <textarea
            id="question"
            ref={inputRef}
            rows={1}
            maxLength={MAX_LENGTH}
            value={draft}
            autoFocus
            placeholder="Ask about invoices or policy"
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                submit(draft);
              }
            }}
          />
          <button type="submit" className="send" aria-label={busy ? "Working" : "Send"} disabled={busy || !draft.trim()}>
            <SendIcon />
          </button>
        </form>
        {empty && (
          <div className="suggestions">
            {EXAMPLES.map((q) => <button key={q} className="suggestion" onClick={() => submit(q)}>{q}</button>)}
          </div>
        )}
        <p className="footnote">
          Each question is answered on its own; earlier questions are not remembered. Check key figures against the evidence.
        </p>
      </div>
    </div>
  );
}
