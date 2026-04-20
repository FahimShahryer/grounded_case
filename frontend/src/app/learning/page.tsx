import { listPatterns, listTemplates } from "@/lib/api";
import { runMinerAction } from "@/actions/learning";

export const dynamic = "force-dynamic";

export default async function LearningPage() {
  const [patterns, templates] = await Promise.all([
    listPatterns().catch(() => []),
    listTemplates().catch(() => []),
  ]);

  return (
    <div>
      <header className="mb-8 flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Learning</h1>
          <p className="mt-1 text-slate-500">
            Operator edits → structured diff → classified signals → mined
            patterns → template version bump → enforced at generation time.
          </p>
        </div>
        <form action={runMinerAction}>
          <button
            type="submit"
            className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700"
          >
            Run miner
          </button>
        </form>
      </header>

      <section className="mb-10">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500 mb-3">
          Patterns ({patterns.length})
        </h2>
        {patterns.length === 0 ? (
          <div className="rounded-lg border border-slate-200 bg-white p-6 text-center text-sm text-slate-500">
            No patterns yet. Run <code>make seed-edits</code> then click{" "}
            <strong>Run miner</strong>.
          </div>
        ) : (
          <ul className="space-y-3">
            {patterns.map((p) => (
              <li
                key={p.id}
                className={`rounded-lg border p-4 ${
                  p.active
                    ? "border-slate-200 bg-white"
                    : "border-slate-200 bg-slate-50 opacity-60"
                }`}
              >
                <div className="flex items-start justify-between gap-4">
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-1 flex-wrap">
                      <span className="font-mono text-xs text-slate-500">
                        #{p.id}
                      </span>
                      <Chip label={`scope: ${p.scope}`} />
                      {p.draft_type ? (
                        <Chip label={`draft: ${p.draft_type}`} tone="indigo" />
                      ) : (
                        <Chip label="draft: (all)" tone="indigo" />
                      )}
                      {p.section_id ? (
                        <Chip label={`section: ${p.section_id}`} tone="slate" />
                      ) : (
                        <Chip label="section: (all)" tone="slate" />
                      )}
                      <Chip
                        label={`v${p.version}`}
                        tone="slate"
                      />
                      {!p.active && <Chip label="inactive" tone="rose" />}
                    </div>
                    <p className="text-sm text-slate-700">
                      <span className="font-medium">WHEN</span> {p.rule_when}
                    </p>
                    <p className="mt-1 text-sm text-slate-900 font-medium">
                      <span className="text-slate-500 font-medium">MUST</span>{" "}
                      {p.rule_must}
                    </p>
                    <div className="mt-2 text-xs text-slate-500">
                      supported by edit
                      {p.supporting_edit_ids.length > 1 ? "s" : ""}{" "}
                      {p.supporting_edit_ids.map((i) => `#${i}`).join(", ")}
                    </div>
                  </div>
                  <div className="text-right">
                    <div className="text-2xl font-semibold tabular-nums">
                      {Math.round(p.confidence * 100)}
                      <span className="text-sm text-slate-500 ml-1">%</span>
                    </div>
                    <div className="text-xs text-slate-500">confidence</div>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section>
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500 mb-3">
          Templates ({templates.length})
        </h2>
        {templates.length === 0 ? (
          <p className="text-sm text-slate-500">
            Templates will appear once the miner has run.
          </p>
        ) : (
          <ul className="space-y-2">
            {templates.map((t) => {
              const rules =
                (t.manifest as { rules?: unknown[] })?.rules ?? [];
              return (
                <li
                  key={t.id}
                  className={`rounded border px-4 py-3 ${
                    t.active
                      ? "border-slate-200 bg-white"
                      : "border-slate-200 bg-slate-50 opacity-70"
                  }`}
                >
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-xs text-slate-500">
                      #{t.id}
                    </span>
                    <Chip label={t.draft_type} tone="indigo" />
                    <Chip label={`v${t.version}`} />
                    {t.active && <Chip label="active" tone="green" />}
                  </div>
                  <div className="mt-1 text-xs text-slate-500">
                    {rules.length} rule{rules.length === 1 ? "" : "s"} ·{" "}
                    {new Date(t.created_at).toLocaleString()}
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </div>
  );
}

function Chip({
  label,
  tone,
}: {
  label: string;
  tone?: "slate" | "indigo" | "rose" | "green";
}) {
  const toneCls = {
    slate: "bg-slate-100 text-slate-700",
    indigo: "bg-indigo-100 text-indigo-800",
    rose: "bg-rose-100 text-rose-800",
    green: "bg-emerald-100 text-emerald-800",
  }[tone ?? "slate"];
  return (
    <span className={`rounded px-2 py-0.5 text-xs font-medium ${toneCls}`}>
      {label}
    </span>
  );
}
