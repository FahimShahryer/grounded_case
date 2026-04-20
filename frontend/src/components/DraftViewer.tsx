"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { PUBLIC_API_BASE } from "@/lib/api";
import type {
  Citation,
  Draft,
  DraftBlock,
  DraftSection,
  DocumentDetail,
  DocumentOut,
  SourceSpan,
} from "@/lib/types";

type Active = {
  span: SourceSpan;
  claim: string;
};

type Props = {
  caseId: number;
  draft: Draft;
  documents: DocumentOut[];
};

export default function DraftViewer({ caseId, draft, documents }: Props) {
  const [active, setActive] = useState<Active | null>(null);
  const [doc, setDoc] = useState<DocumentDetail | null>(null);
  const [loading, setLoading] = useState(false);

  const filenameToDocId = useMemo(() => {
    const m = new Map<string, number>();
    for (const d of documents) m.set(d.filename, d.id);
    return m;
  }, [documents]);

  useEffect(() => {
    if (!active) return;
    const docId = filenameToDocId.get(active.span.file);
    if (!docId) {
      setDoc(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    fetch(`${PUBLIC_API_BASE}/api/documents/${docId}`, { cache: "no-store" })
      .then((r) => r.json() as Promise<DocumentDetail>)
      .then((d) => {
        if (!cancelled) setDoc(d);
      })
      .catch(() => {
        if (!cancelled) setDoc(null);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [active, filenameToDocId]);

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,_3fr)_minmax(0,_2fr)]">
      {/* Left — the draft */}
      <article className="rounded-lg border border-slate-200 bg-white p-6">
        <header className="mb-6 border-b border-slate-200 pb-4">
          <div className="flex items-center justify-between">
            <h1 className="text-xl font-semibold tracking-tight">
              {draft.draft_type.replace(/_/g, " ")}
            </h1>
            <div className="flex gap-2">
              <Link
                href={`/cases/${caseId}/drafts/${draft.id}/edit`}
                className="rounded border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium hover:bg-slate-50"
              >
                Edit
              </Link>
              <Link
                href={`/cases/${caseId}`}
                className="rounded border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium hover:bg-slate-50"
              >
                Back
              </Link>
            </div>
          </div>
          <div className="mt-2 text-xs text-slate-500 font-mono">
            Draft #{draft.id} · {draft.model} · v{draft.template_version} ·{" "}
            {new Date(draft.created_at).toLocaleString()}
          </div>
          {Object.keys(draft.content.header ?? {}).length > 0 && (
            <dl className="mt-3 grid grid-cols-2 gap-x-6 gap-y-1 text-sm">
              {Object.entries(draft.content.header).map(([k, v]) => (
                <div key={k} className="contents">
                  <dt className="text-slate-500 capitalize">
                    {k.replace(/_/g, " ")}
                  </dt>
                  <dd className="text-slate-800">{v}</dd>
                </div>
              ))}
            </dl>
          )}
        </header>

        <div className="space-y-8">
          {draft.content.sections.map((section) => (
            <DraftSectionView
              key={section.id}
              section={section}
              onCitationClick={(span, claim) => setActive({ span, claim })}
              activeSpan={active?.span ?? null}
            />
          ))}
        </div>
      </article>

      {/* Right — source panel */}
      <aside className="sticky top-4 self-start rounded-lg border border-slate-200 bg-white p-6 max-h-[calc(100vh-6rem)] overflow-hidden flex flex-col">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500 mb-3">
          Source
        </h2>
        {!active && (
          <p className="text-sm text-slate-500">
            Click a citation to see the exact lines from the source document.
          </p>
        )}
        {active && (
          <div className="flex-1 flex flex-col min-h-0">
            <div className="text-sm mb-2">
              <div className="font-medium">{active.claim}</div>
              <div className="text-xs text-slate-500 font-mono flex items-center gap-2">
                <span>
                  {active.span.file}:L{active.span.line_start}–L
                  {active.span.line_end}
                </span>
                {doc?.storage_key && (
                  <a
                    href={`${PUBLIC_API_BASE}/api/documents/${doc.id}/download`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="rounded bg-indigo-100 px-1.5 py-0.5 font-medium text-indigo-800 hover:bg-indigo-200"
                    title="Open original PDF from MinIO"
                  >
                    open PDF ↗
                  </a>
                )}
              </div>
            </div>
            {loading && <p className="text-sm text-slate-500">Loading…</p>}
            {doc && (
              <SourceLines
                doc={doc}
                startLine={active.span.line_start}
                endLine={active.span.line_end}
              />
            )}
            {!loading && !doc && (
              <p className="text-sm text-rose-600">
                Could not load {active.span.file}.
              </p>
            )}
          </div>
        )}
      </aside>
    </div>
  );
}

// ---------- Draft section / block rendering ----------

function DraftSectionView({
  section,
  onCitationClick,
  activeSpan,
}: {
  section: DraftSection;
  onCitationClick: (span: SourceSpan, claim: string) => void;
  activeSpan: SourceSpan | null;
}) {
  return (
    <section>
      <h2 className="text-lg font-semibold text-slate-800 mb-3">
        {section.heading}
      </h2>
      {section.abstained && (
        <p className="italic text-slate-500">
          No evidence of this found in the source materials.
        </p>
      )}
      {section.body && (
        <p className="mb-3 text-slate-700 leading-relaxed">{section.body}</p>
      )}
      <div className="space-y-4">
        {section.blocks.map((block, i) => (
          <DraftBlockView
            key={i}
            block={block}
            onCitationClick={onCitationClick}
            activeSpan={activeSpan}
          />
        ))}
      </div>
    </section>
  );
}

function DraftBlockView({
  block,
  onCitationClick,
  activeSpan,
}: {
  block: DraftBlock;
  onCitationClick: (span: SourceSpan, claim: string) => void;
  activeSpan: SourceSpan | null;
}) {
  return (
    <div className="rounded-md border border-slate-200 bg-slate-50 p-4">
      {(block.title || block.badges.length > 0) && (
        <div className="flex flex-wrap items-center gap-2 mb-2">
          {block.title && (
            <h3 className="font-semibold text-slate-900">{block.title}</h3>
          )}
          {block.badges.map((b) => (
            <span
              key={b}
              className={`rounded px-2 py-0.5 text-xs font-medium ${badgeColor(b)}`}
            >
              {b}
            </span>
          ))}
        </div>
      )}
      {block.fields.length > 0 && (
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
          {block.fields.map((f, i) => (
            <div key={i} className="contents">
              <dt className="text-slate-500">{f.key}</dt>
              <dd className="font-medium">{f.value}</dd>
            </div>
          ))}
        </dl>
      )}
      {block.notes && (
        <blockquote className="mt-2 border-l-2 border-slate-300 pl-3 text-sm text-slate-600 italic">
          {block.notes}
        </blockquote>
      )}
      {block.action_items.length > 0 && (
        <ul className="mt-2 text-sm space-y-1">
          {block.action_items.map((a, i) => (
            <li key={i}>☐ {a}</li>
          ))}
        </ul>
      )}
      {block.citations.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-2">
          {block.citations.flatMap((c, ci) =>
            c.spans.map((span, si) => (
              <CitationChip
                key={`${ci}-${si}`}
                citation={c}
                span={span}
                active={isSameSpan(activeSpan, span)}
                onClick={() => onCitationClick(span, c.claim)}
              />
            )),
          )}
        </div>
      )}
    </div>
  );
}

function CitationChip({
  citation,
  span,
  active,
  onClick,
}: {
  citation: Citation;
  span: SourceSpan;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={citation.claim}
      className={`rounded border px-2 py-0.5 text-xs font-mono transition ${
        active
          ? "border-indigo-500 bg-indigo-50 text-indigo-900"
          : "border-slate-300 bg-white text-slate-700 hover:border-slate-500"
      }`}
    >
      {span.file}:L{span.line_start}
      {span.line_end !== span.line_start ? `-${span.line_end}` : ""}
    </button>
  );
}

function SourceLines({
  doc,
  startLine,
  endLine,
}: {
  doc: DocumentDetail;
  startLine: number;
  endLine: number;
}) {
  const text = doc.cleaned_text ?? doc.raw_text ?? "";
  const lines = text.split("\n");
  return (
    <div className="flex-1 overflow-auto rounded border border-slate-200 bg-slate-50 font-mono text-xs">
      <pre className="p-0 m-0">
        {lines.map((line, i) => {
          const n = i + 1;
          const highlight = n >= startLine && n <= endLine;
          return (
            <div
              key={n}
              id={`L${n}`}
              className={`flex ${highlight ? "bg-yellow-100" : ""}`}
            >
              <span className="w-10 flex-shrink-0 text-right pr-2 text-slate-400 select-none border-r border-slate-200">
                {n}
              </span>
              <span className="whitespace-pre-wrap px-2 py-0.5 flex-1">
                {line || " "}
              </span>
            </div>
          );
        })}
      </pre>
    </div>
  );
}

function isSameSpan(a: SourceSpan | null, b: SourceSpan): boolean {
  if (!a) return false;
  return (
    a.file === b.file &&
    a.line_start === b.line_start &&
    a.line_end === b.line_end
  );
}

function badgeColor(badge: string): string {
  const upper = badge.toUpperCase();
  if (/URGENT|ACTION REQUIRED|DELINQUENT|CONFLICT/.test(upper))
    return "bg-rose-100 text-rose-700";
  if (/HIGH/.test(upper)) return "bg-amber-100 text-amber-800";
  if (/ASSIGNED|ACTIVE TRANSFER/.test(upper))
    return "bg-indigo-100 text-indigo-800";
  return "bg-slate-200 text-slate-800";
}
