import Link from "next/link";
import NewCaseForm from "./NewCaseForm";

export const metadata = { title: "New case" };

export default function NewCasePage() {
  return (
    <div className="max-w-2xl">
      <Link href="/" className="text-sm text-slate-500 hover:text-slate-900">
        ← All cases
      </Link>
      <div className="mt-3 mb-6">
        <h1 className="text-2xl font-semibold tracking-tight">New case</h1>
        <p className="mt-1 text-sm text-slate-600">
          Only the docket number, borrower, and property address are required.
          Everything else is optional — fill in what you have.
        </p>
      </div>
      <NewCaseForm />
    </div>
  );
}
