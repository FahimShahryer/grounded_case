"use client";

import Link from "next/link";
import { useState, useTransition } from "react";
import { saveEditAction } from "@/actions/edits";
import type { Draft, DraftContent, DraftSection, DraftBlock } from "@/lib/types";

type Props = {
  caseId: number;
  draft: Draft;
};

export default function DraftEditor({ caseId, draft }: Props) {
  const [content, setContent] = useState<DraftContent>(() =>
    structuredClone(draft.content),
  );
  const [rationale, setRationale] = useState("");
  const [pending, start] = useTransition();
  const [error, setError] = useState<string | null>(null);

  function updateSection(idx: number, patch: Partial<DraftSection>) {
    setContent((c) => {
      const sections = [...c.sections];
      sections[idx] = { ...sections[idx], ...patch };
      return { ...c, sections };
    });
  }

  function updateBlock(
    si: number,
    bi: number,
    patch: Partial<DraftBlock>,
  ) {
    setContent((c) => {
      const sections = [...c.sections];
      const blocks = [...sections[si].blocks];
      blocks[bi] = { ...blocks[bi], ...patch };
      sections[si] = { ...sections[si], blocks };
      return { ...c, sections };
    });
  }

  function submit() {
    setError(null);
    start(async () => {
      try {
        await saveEditAction(caseId, draft.id, content, rationale || null);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    });
  }

  return (
    <div className="space-y-6">
      <header className="flex items-center justify-between border-b border-slate-200 pb-4">
        <div>
          <h1 className="text-xl font-semibold">
            Editing: {draft.draft_type.replace(/_/g, " ")}
          </h1>
          <p className="text-xs text-slate-500 font-mono">
            Draft #{draft.id}
          </p>
        </div>
        <div className="flex gap-2">
          <Link
            href={`/cases/${caseId}/drafts/${draft.id}`}
            className="rounded border border-slate-300 bg-white px-3 py-1.5 text-sm hover:bg-slate-50"
          >
            Cancel
          </Link>
          <button
            type="button"
            onClick={submit}
            disabled={pending}
            className="rounded bg-slate-900 px-4 py-1.5 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-50"
          >
            {pending ? "Saving…" : "Save edit"}
          </button>
        </div>
      </header>

      {error && (
        <div className="rounded border border-rose-200 bg-rose-50 px-4 py-2 text-sm text-rose-700">
          {error}
        </div>
      )}

      <div>
        <label className="block text-sm font-medium mb-1">
          Rationale (optional)
        </label>
        <textarea
          value={rationale}
          onChange={(e) => setRationale(e.target.value)}
          rows={2}
          placeholder="Why you're making these edits — helps the learning loop."
          className="w-full rounded border border-slate-300 px-3 py-2 text-sm"
        />
      </div>

      <div className="space-y-8">
        {content.sections.map((section, si) => (
          <SectionEditor
            key={section.id}
            section={section}
            onChange={(patch) => updateSection(si, patch)}
            onBlockChange={(bi, patch) => updateBlock(si, bi, patch)}
            onAddBlock={() =>
              updateSection(si, {
                blocks: [
                  ...section.blocks,
                  {
                    title: "",
                    fields: [],
                    badges: [],
                    notes: null,
                    action_items: [],
                    citations: [],
                  },
                ],
              })
            }
            onRemoveBlock={(bi) =>
              updateSection(si, {
                blocks: section.blocks.filter((_, i) => i !== bi),
              })
            }
          />
        ))}
      </div>

      <div className="sticky bottom-4 flex justify-end">
        <button
          type="button"
          onClick={submit}
          disabled={pending}
          className="rounded bg-slate-900 px-5 py-2 text-sm font-medium text-white hover:bg-slate-700 shadow disabled:opacity-50"
        >
          {pending ? "Saving…" : "Save edit"}
        </button>
      </div>
    </div>
  );
}

function SectionEditor({
  section,
  onChange,
  onBlockChange,
  onAddBlock,
  onRemoveBlock,
}: {
  section: DraftSection;
  onChange: (patch: Partial<DraftSection>) => void;
  onBlockChange: (bi: number, patch: Partial<DraftBlock>) => void;
  onAddBlock: () => void;
  onRemoveBlock: (bi: number) => void;
}) {
  return (
    <section className="rounded-lg border border-slate-200 bg-white p-5">
      <input
        type="text"
        value={section.heading}
        onChange={(e) => onChange({ heading: e.target.value })}
        className="w-full text-lg font-semibold bg-transparent border-b border-transparent focus:border-slate-300 outline-none mb-3"
      />
      {section.body !== null && (
        <textarea
          value={section.body ?? ""}
          onChange={(e) => onChange({ body: e.target.value || null })}
          rows={2}
          placeholder="Section body (prose)"
          className="w-full rounded border border-slate-200 px-3 py-2 text-sm mb-3"
        />
      )}
      <div className="space-y-4">
        {section.blocks.map((block, bi) => (
          <BlockEditor
            key={bi}
            block={block}
            onChange={(patch) => onBlockChange(bi, patch)}
            onRemove={() => onRemoveBlock(bi)}
          />
        ))}
        <button
          type="button"
          onClick={onAddBlock}
          className="text-sm text-slate-600 hover:text-slate-900 underline"
        >
          + Add block
        </button>
      </div>
    </section>
  );
}

function BlockEditor({
  block,
  onChange,
  onRemove,
}: {
  block: DraftBlock;
  onChange: (patch: Partial<DraftBlock>) => void;
  onRemove: () => void;
}) {
  const [newField, setNewField] = useState({ key: "", value: "" });
  const [newBadge, setNewBadge] = useState("");
  const [newAction, setNewAction] = useState("");

  return (
    <div className="rounded-md border border-slate-200 bg-slate-50 p-4">
      <div className="flex gap-2 items-start mb-2">
        <input
          type="text"
          value={block.title ?? ""}
          onChange={(e) => onChange({ title: e.target.value || null })}
          placeholder="Block title"
          className="flex-1 font-semibold bg-white border border-slate-200 rounded px-2 py-1 text-sm"
        />
        <button
          type="button"
          onClick={onRemove}
          className="text-xs text-rose-600 hover:text-rose-800"
        >
          remove
        </button>
      </div>

      {/* Badges */}
      <div className="mb-2">
        <div className="text-xs font-medium text-slate-500 mb-1">Badges</div>
        <div className="flex flex-wrap gap-2 items-center">
          {block.badges.map((b, i) => (
            <span
              key={i}
              className="inline-flex items-center gap-1 rounded bg-slate-200 px-2 py-0.5 text-xs"
            >
              {b}
              <button
                type="button"
                onClick={() =>
                  onChange({
                    badges: block.badges.filter((_, j) => j !== i),
                  })
                }
                className="text-slate-500 hover:text-rose-600"
              >
                ×
              </button>
            </span>
          ))}
          <input
            type="text"
            value={newBadge}
            onChange={(e) => setNewBadge(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && newBadge.trim()) {
                e.preventDefault();
                onChange({ badges: [...block.badges, newBadge.trim()] });
                setNewBadge("");
              }
            }}
            placeholder="+ badge"
            className="rounded border border-slate-300 bg-white px-2 py-0.5 text-xs w-24"
          />
        </div>
      </div>

      {/* Fields */}
      <div className="mb-2">
        <div className="text-xs font-medium text-slate-500 mb-1">Fields</div>
        <div className="space-y-1">
          {block.fields.map((f, i) => (
            <div key={i} className="flex gap-2">
              <input
                type="text"
                value={f.key}
                onChange={(e) => {
                  const fields = [...block.fields];
                  fields[i] = { ...fields[i], key: e.target.value };
                  onChange({ fields });
                }}
                placeholder="key"
                className="w-1/3 rounded border border-slate-200 bg-white px-2 py-1 text-xs"
              />
              <input
                type="text"
                value={f.value}
                onChange={(e) => {
                  const fields = [...block.fields];
                  fields[i] = { ...fields[i], value: e.target.value };
                  onChange({ fields });
                }}
                placeholder="value"
                className="flex-1 rounded border border-slate-200 bg-white px-2 py-1 text-xs"
              />
              <button
                type="button"
                onClick={() =>
                  onChange({
                    fields: block.fields.filter((_, j) => j !== i),
                  })
                }
                className="text-xs text-rose-600 hover:text-rose-800"
              >
                ×
              </button>
            </div>
          ))}
          <div className="flex gap-2">
            <input
              type="text"
              value={newField.key}
              onChange={(e) =>
                setNewField({ ...newField, key: e.target.value })
              }
              placeholder="new key"
              className="w-1/3 rounded border border-slate-300 bg-white px-2 py-1 text-xs"
            />
            <input
              type="text"
              value={newField.value}
              onChange={(e) =>
                setNewField({ ...newField, value: e.target.value })
              }
              placeholder="new value"
              className="flex-1 rounded border border-slate-300 bg-white px-2 py-1 text-xs"
            />
            <button
              type="button"
              onClick={() => {
                if (newField.key.trim()) {
                  onChange({ fields: [...block.fields, newField] });
                  setNewField({ key: "", value: "" });
                }
              }}
              className="text-xs text-slate-700 hover:text-slate-900"
            >
              + add
            </button>
          </div>
        </div>
      </div>

      {/* Notes */}
      <div className="mb-2">
        <div className="text-xs font-medium text-slate-500 mb-1">Notes</div>
        <textarea
          value={block.notes ?? ""}
          onChange={(e) => onChange({ notes: e.target.value || null })}
          rows={2}
          className="w-full rounded border border-slate-200 bg-white px-2 py-1 text-xs"
        />
      </div>

      {/* Action items */}
      <div className="mb-2">
        <div className="text-xs font-medium text-slate-500 mb-1">
          Action items
        </div>
        <ul className="space-y-1">
          {block.action_items.map((a, i) => (
            <li key={i} className="flex gap-2">
              <input
                type="text"
                value={a}
                onChange={(e) => {
                  const items = [...block.action_items];
                  items[i] = e.target.value;
                  onChange({ action_items: items });
                }}
                className="flex-1 rounded border border-slate-200 bg-white px-2 py-1 text-xs"
              />
              <button
                type="button"
                onClick={() =>
                  onChange({
                    action_items: block.action_items.filter(
                      (_, j) => j !== i,
                    ),
                  })
                }
                className="text-xs text-rose-600 hover:text-rose-800"
              >
                ×
              </button>
            </li>
          ))}
          <li className="flex gap-2">
            <input
              type="text"
              value={newAction}
              onChange={(e) => setNewAction(e.target.value)}
              placeholder="+ new action item"
              className="flex-1 rounded border border-slate-300 bg-white px-2 py-1 text-xs"
              onKeyDown={(e) => {
                if (e.key === "Enter" && newAction.trim()) {
                  e.preventDefault();
                  onChange({
                    action_items: [...block.action_items, newAction.trim()],
                  });
                  setNewAction("");
                }
              }}
            />
          </li>
        </ul>
      </div>

      {block.citations.length > 0 && (
        <div className="text-xs text-slate-500">
          <span className="font-medium">Citations (read-only):</span>{" "}
          {block.citations
            .flatMap((c) => c.spans)
            .map(
              (s, i) =>
                `${s.file}:L${s.line_start}${s.line_end !== s.line_start ? `-${s.line_end}` : ""}`,
            )
            .join(" · ")}
        </div>
      )}
    </div>
  );
}
