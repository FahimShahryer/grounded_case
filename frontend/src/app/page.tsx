import Link from "next/link";
import { listCases } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function Home() {
  let cases: Awaited<ReturnType<typeof listCases>> = [];
  let error: string | null = null;
  try {
    cases = await listCases();
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  return (
    <div>
      <div className="mb-8 flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Cases</h1>
          <p className="text-slate-500 mt-1">
            Each case is a folder of documents the pipeline turns into grounded
            drafts.
          </p>
        </div>
        <Link
          href="/cases/new"
          className="shrink-0 rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700"
        >
          + New case
        </Link>
      </div>

      {error && (
        <div className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
          Backend unreachable: {error}
        </div>
      )}

      {!error && cases.length === 0 && (
        <div className="rounded-lg border border-slate-200 bg-white px-6 py-10 text-center">
          <p className="text-slate-500">
            No cases yet. Click{" "}
            <Link href="/cases/new" className="font-medium text-slate-900 underline">
              + New case
            </Link>{" "}
            to add one, or run{" "}
            <code className="font-mono bg-slate-100 px-1.5 py-0.5 rounded">
              make seed
            </code>{" "}
            to load the sample Rodriguez fixtures.
          </p>
        </div>
      )}

      <ul className="grid gap-4 sm:grid-cols-2">
        {cases.map((c) => (
          <li key={c.id}>
            <Link
              href={`/cases/${c.id}`}
              className="block rounded-lg border border-slate-200 bg-white p-5 hover:border-slate-400 hover:shadow-sm transition"
            >
              <div className="flex items-center justify-between">
                <span className="font-mono text-sm text-slate-500">
                  {c.case_number}
                </span>
                {c.current_status && (
                  <span className="rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-700">
                    {c.current_status}
                  </span>
                )}
              </div>
              <h2 className="mt-2 text-lg font-semibold">{c.borrower}</h2>
              <p className="mt-1 text-sm text-slate-600">{c.property_address}</p>
              {(c.county || c.state) && (
                <p className="mt-1 text-xs text-slate-500">
                  {[c.county, c.state].filter(Boolean).join(", ")}
                </p>
              )}
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
