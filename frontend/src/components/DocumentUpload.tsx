"use client";

import { useRef, useState, useTransition } from "react";
import { uploadDocumentsAction } from "@/actions/documents";

type UploadResult = {
  filename: string;
  ok: boolean;
  id?: number;
  doc_type?: string;
  engine?: string;
  error?: string;
};

type Props = { caseId: number };

export default function DocumentUpload({ caseId }: Props) {
  const [isPending, startTransition] = useTransition();
  const [results, setResults] = useState<UploadResult[] | null>(null);
  const [selected, setSelected] = useState<File[]>([]);
  const inputRef = useRef<HTMLInputElement | null>(null);

  function onFilesPicked(e: React.ChangeEvent<HTMLInputElement>) {
    const list = e.target.files;
    setSelected(list ? Array.from(list) : []);
    setResults(null);
  }

  function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (selected.length === 0) return;
    const fd = new FormData();
    for (const f of selected) fd.append("files", f, f.name);
    startTransition(async () => {
      const { results: r } = await uploadDocumentsAction(caseId, fd);
      setResults(r);
      setSelected([]);
      if (inputRef.current) inputRef.current.value = "";
    });
  }

  return (
    <form
      onSubmit={onSubmit}
      className="rounded-lg border border-slate-200 bg-white p-4"
    >
      <div className="flex items-center gap-3 flex-wrap">
        <input
          ref={inputRef}
          type="file"
          name="files"
          multiple
          accept=".pdf,.png,.jpg,.jpeg,.txt"
          onChange={onFilesPicked}
          className="block text-sm text-slate-700
            file:mr-3 file:py-1.5 file:px-3 file:rounded file:border-0
            file:text-xs file:font-medium file:bg-slate-100
            file:text-slate-700 hover:file:bg-slate-200"
          disabled={isPending}
        />
        <button
          type="submit"
          disabled={isPending || selected.length === 0}
          className="rounded-lg bg-slate-900 px-4 py-1.5 text-sm font-medium
            text-white hover:bg-slate-700 disabled:opacity-40
            disabled:cursor-not-allowed"
        >
          {isPending
            ? `Uploading ${selected.length}…`
            : selected.length > 0
              ? `Upload ${selected.length} file${selected.length > 1 ? "s" : ""}`
              : "Upload"}
        </button>
        <span className="text-xs text-slate-500">
          PDF / PNG / JPG / TXT. Scans route through Tesseract OCR.
        </span>
      </div>

      {/* pending list (filenames selected but not uploaded) */}
      {selected.length > 0 && !isPending && !results && (
        <ul className="mt-3 text-xs text-slate-600 space-y-0.5">
          {selected.map((f) => (
            <li key={f.name} className="font-mono truncate">
              ▸ {f.name}{" "}
              <span className="text-slate-400">
                ({Math.round(f.size / 1024)} KB)
              </span>
            </li>
          ))}
        </ul>
      )}

      {/* results after upload */}
      {results && results.length > 0 && (
        <ul className="mt-3 text-xs space-y-1">
          {results.map((r) => (
            <li
              key={r.filename}
              className={`rounded px-2 py-1 font-mono ${
                r.ok
                  ? "bg-emerald-50 text-emerald-900"
                  : "bg-rose-50 text-rose-900"
              }`}
            >
              {r.ok ? "✓" : "✗"} {r.filename}
              {r.ok && r.doc_type && (
                <span className="ml-2 text-slate-600">
                  → {r.doc_type} · {r.engine ?? "text"}
                </span>
              )}
              {!r.ok && r.error && (
                <span className="ml-2 text-rose-700">{r.error}</span>
              )}
            </li>
          ))}
        </ul>
      )}
    </form>
  );
}
