"use client";

import { useActionState } from "react";
import { createCaseAction, type CreateCaseState } from "@/actions/cases";

const initial: CreateCaseState = {};

export default function NewCaseForm() {
  const [state, formAction, pending] = useActionState(createCaseAction, initial);
  const v = state.values;

  return (
    <form action={formAction} className="rounded-lg border border-slate-200 bg-white p-6">
      {state.error && (
        <div className="mb-4 rounded border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800">
          {state.error}
        </div>
      )}

      <fieldset className="grid gap-4 sm:grid-cols-2" disabled={pending}>
        <Field
          label="Case number *"
          name="case_number"
          placeholder="2026-FC-99999"
          defaultValue={v?.case_number ?? ""}
          required
          help="Legal docket number. Must be unique."
        />
        <Field
          label="Borrower *"
          name="borrower"
          placeholder="Smith, John"
          defaultValue={v?.borrower ?? ""}
          required
        />
        <Field
          label="Property address *"
          name="property_address"
          placeholder="100 Main St, Miami, FL"
          defaultValue={v?.property_address ?? ""}
          required
          full
        />
        <Field
          label="County"
          name="county"
          placeholder="Miami-Dade"
          defaultValue={v?.county ?? ""}
        />
        <Field
          label="State"
          name="state"
          placeholder="FL"
          defaultValue={v?.state ?? ""}
          maxLength={8}
        />
        <Field
          label="Servicer"
          name="servicer"
          placeholder="Wells Fargo"
          defaultValue={v?.servicer ?? ""}
        />
        <Field
          label="Loan number"
          name="loan_number"
          placeholder="2021-0123456"
          defaultValue={v?.loan_number ?? ""}
        />
        <Field
          label="Loan amount (USD)"
          name="loan_amount"
          type="number"
          step="0.01"
          placeholder="445000.00"
          defaultValue={v?.loan_amount?.toString() ?? ""}
        />
        <Field
          label="Loan date"
          name="loan_date"
          type="date"
          defaultValue={v?.loan_date ?? ""}
        />
        <Field
          label="Default date"
          name="default_date"
          type="date"
          defaultValue={v?.default_date ?? ""}
        />
        <Field
          label="Current status"
          name="current_status"
          placeholder="pre_filing"
          defaultValue={v?.current_status ?? ""}
        />
        <div className="sm:col-span-2">
          <label className="block text-sm font-medium text-slate-700 mb-1">
            Notes
          </label>
          <textarea
            name="notes"
            rows={3}
            defaultValue={v?.notes ?? ""}
            className="w-full rounded border border-slate-300 px-3 py-1.5 text-sm focus:border-slate-500 focus:outline-none"
            placeholder="Anything else worth capturing…"
          />
        </div>
      </fieldset>

      <div className="mt-6 flex items-center gap-3">
        <button
          type="submit"
          disabled={pending}
          className="rounded-lg bg-slate-900 px-5 py-2 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-40"
        >
          {pending ? "Creating…" : "Create case"}
        </button>
        <span className="text-xs text-slate-500">
          After creation you'll land on the case page and can upload documents.
        </span>
      </div>
    </form>
  );
}

function Field({
  label,
  name,
  type = "text",
  placeholder,
  defaultValue,
  required,
  help,
  full,
  maxLength,
  step,
}: {
  label: string;
  name: string;
  type?: string;
  placeholder?: string;
  defaultValue?: string;
  required?: boolean;
  help?: string;
  full?: boolean;
  maxLength?: number;
  step?: string;
}) {
  return (
    <div className={full ? "sm:col-span-2" : undefined}>
      <label className="block text-sm font-medium text-slate-700 mb-1">
        {label}
      </label>
      <input
        type={type}
        name={name}
        placeholder={placeholder}
        defaultValue={defaultValue}
        required={required}
        maxLength={maxLength}
        step={step}
        className="w-full rounded border border-slate-300 px-3 py-1.5 text-sm focus:border-slate-500 focus:outline-none"
      />
      {help && <p className="mt-1 text-xs text-slate-500">{help}</p>}
    </div>
  );
}
