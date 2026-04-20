import Link from "next/link";
import { getCase, listDocuments, listFacts, listDraftsForCase, PUBLIC_API_BASE } from "@/lib/api";
import { generateDraftAction, runProcessAction } from "@/actions/drafts";
import type { OcrMeta } from "@/lib/types";
import DocumentUpload from "@/components/DocumentUpload";

function OcrBadge({ ocr }: { ocr: OcrMeta | undefined }) {
  if (!ocr) return null;
  if (ocr.engine === "text") return null; // no need to badge plain-text docs

  const isScan = ocr.engine === "tesseract";
  const label = isScan ? "OCR" : "PDF";
  const title = isScan
    ? `Scanned — Tesseract (${ocr.pages ?? 1} page${(ocr.pages ?? 1) > 1 ? "s" : ""}` +
      (ocr.mean_confidence != null ? `, ${ocr.mean_confidence.toFixed(0)}% conf` : "") +
      ")"
    : `Text extracted via pdfplumber (${ocr.pages ?? 1} page${(ocr.pages ?? 1) > 1 ? "s" : ""})`;
  const cls = isScan
    ? "bg-amber-100 text-amber-800"
    : "bg-emerald-100 text-emerald-800";
  return (
    <span
      title={title}
      className={`rounded px-2 py-0.5 text-xs font-medium font-mono ${cls}`}
    >
      {label}
    </span>
  );
}

export const dynamic = "force-dynamic";

export default async function CaseDetail({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const caseId = Number(id);

  const [c, docs, facts, drafts] = await Promise.all([
    getCase(caseId),
    listDocuments(caseId),
    listFacts(caseId).catch(() => []),
    listDraftsForCase(caseId).catch(() => []),
  ]);

  const factsByType: Record<string, typeof facts> = {};
  for (const f of facts) {
    (factsByType[f.fact_type] ??= []).push(f);
  }

  return (
    <div>
      <Link href="/" className="text-sm text-slate-500 hover:text-slate-900">
        ← All cases
      </Link>

      <header className="mt-3 mb-8 border-b border-slate-200 pb-6">
        <div className="flex items-center gap-3">
          <h1 className="text-2xl font-semibold tracking-tight">{c.borrower}</h1>
          <span className="font-mono text-sm text-slate-500">
            {c.case_number}
          </span>
        </div>
        <p className="mt-1 text-slate-700">{c.property_address}</p>
        {(c.county || c.state) && (
          <p className="text-sm text-slate-500">
            {[c.county, c.state].filter(Boolean).join(", ")}
          </p>
        )}
        {c.servicer && (
          <p className="mt-1 text-sm text-slate-500">
            Servicer: {c.servicer}
          </p>
        )}
      </header>

      {/* Actions */}
      <div className="grid gap-6 md:grid-cols-3 mb-8">
        <form action={runProcessAction}>
          <input type="hidden" name="case_id" value={caseId} />
          <button
            type="submit"
            className="w-full rounded-lg border border-slate-300 bg-white px-4 py-3 text-sm font-medium hover:bg-slate-50"
          >
            Re-run processing pipeline
          </button>
        </form>
        <form action={generateDraftAction}>
          <input type="hidden" name="case_id" value={caseId} />
          <input type="hidden" name="draft_type" value="title_review_summary" />
          <button
            type="submit"
            className="w-full rounded-lg bg-slate-900 px-4 py-3 text-sm font-medium text-white hover:bg-slate-700"
          >
            Generate Title Review Summary
          </button>
        </form>
        <form action={generateDraftAction}>
          <input type="hidden" name="case_id" value={caseId} />
          <input type="hidden" name="draft_type" value="case_status_memo" />
          <button
            type="submit"
            className="w-full rounded-lg bg-slate-900 px-4 py-3 text-sm font-medium text-white hover:bg-slate-700"
          >
            Generate Case Status Memo
          </button>
        </form>
      </div>

      {/* Drafts */}
      <section className="mb-10">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500 mb-3">
          Drafts
        </h2>
        {drafts.length === 0 ? (
          <p className="text-sm text-slate-500">
            No drafts yet — click a Generate button above.
          </p>
        ) : (
          <ul className="space-y-2">
            {drafts.map((d) => (
              <li key={d.id}>
                <Link
                  href={`/cases/${caseId}/drafts/${d.id}`}
                  className="flex items-center justify-between rounded border border-slate-200 bg-white px-4 py-3 hover:border-slate-400"
                >
                  <div>
                    <div className="font-medium">
                      {d.draft_type.replace(/_/g, " ")}
                    </div>
                    <div className="text-xs text-slate-500">
                      v{d.template_version} · {d.model} ·{" "}
                      {new Date(d.created_at).toLocaleString()}
                    </div>
                  </div>
                  <span className="text-sm text-slate-400">#{d.id} ›</span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* Documents */}
      <section className="mb-10">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
            Documents ({docs.length})
          </h2>
        </div>
        <div className="mb-3">
          <DocumentUpload caseId={caseId} />
        </div>
        <ul className="grid gap-2 sm:grid-cols-2">
          {docs.map((d) => (
            <li
              key={d.id}
              className="rounded border border-slate-200 bg-white px-4 py-3"
            >
              <div className="flex items-center justify-between gap-2">
                <span className="font-mono text-xs truncate">{d.filename}</span>
                <div className="flex items-center gap-1.5 flex-shrink-0">
                  <OcrBadge ocr={d.meta?.ocr} />
                  <span className="rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-700">
                    {d.doc_type}
                  </span>
                  {d.storage_key && (
                    <a
                      href={`${PUBLIC_API_BASE}/api/documents/${d.id}/download`}
                      target="_blank"
                      rel="noopener noreferrer"
                      title="Open original file from MinIO"
                      className="rounded bg-indigo-100 px-2 py-0.5 text-xs font-medium text-indigo-800 hover:bg-indigo-200"
                    >
                      ↗
                    </a>
                  )}
                </div>
              </div>
            </li>
          ))}
        </ul>
      </section>

      {/* Facts */}
      <section>
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500 mb-3">
          Canonical facts ({facts.length})
        </h2>
        {Object.entries(factsByType).map(([type, group]) => (
          <div key={type} className="mb-4">
            <h3 className="text-sm font-semibold text-slate-700 mb-2">
              {type} <span className="text-slate-400">({group.length})</span>
            </h3>
            <ul className="space-y-1 text-sm">
              {group.map((f) => (
                <li
                  key={f.id}
                  className="rounded border border-slate-200 bg-white px-3 py-2 font-mono text-xs overflow-hidden"
                >
                  <span className="text-slate-500">{f.dedup_key}</span>
                  {f.evidence.length > 0 && (
                    <span className="ml-2 text-slate-400">
                      ← {f.evidence.length} source
                      {f.evidence.length > 1 ? "s" : ""}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </section>
    </div>
  );
}
