"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { createCase, type CaseCreateInput } from "@/lib/api";

/**
 * Server action: create a new case from the /cases/new form.
 *
 * Success → revalidate the case list and redirect to the new case's detail page.
 * Failure (e.g. duplicate case_number) → return an error state the form re-renders.
 */
export type CreateCaseState = {
  error?: string;
  values?: CaseCreateInput;
};

function nonEmpty(v: FormDataEntryValue | null): string | null {
  if (v === null) return null;
  const s = String(v).trim();
  return s.length ? s : null;
}

function numOrNull(v: FormDataEntryValue | null): number | null {
  const s = nonEmpty(v);
  if (s === null) return null;
  const n = Number(s);
  return Number.isFinite(n) ? n : null;
}

export async function createCaseAction(
  _prev: CreateCaseState,
  formData: FormData,
): Promise<CreateCaseState> {
  const input: CaseCreateInput = {
    case_number: (nonEmpty(formData.get("case_number")) ?? "").toString(),
    borrower: (nonEmpty(formData.get("borrower")) ?? "").toString(),
    property_address: (nonEmpty(formData.get("property_address")) ?? "").toString(),
    county: nonEmpty(formData.get("county")),
    state: nonEmpty(formData.get("state")),
    servicer: nonEmpty(formData.get("servicer")),
    loan_number: nonEmpty(formData.get("loan_number")),
    loan_amount: numOrNull(formData.get("loan_amount")),
    loan_date: nonEmpty(formData.get("loan_date")),
    default_date: nonEmpty(formData.get("default_date")),
    current_status: nonEmpty(formData.get("current_status")),
    notes: nonEmpty(formData.get("notes")),
  };

  if (!input.case_number || !input.borrower || !input.property_address) {
    return {
      error: "case_number, borrower, and property_address are required.",
      values: input,
    };
  }

  let created;
  try {
    created = await createCase(input);
  } catch (e) {
    return {
      error: e instanceof Error ? e.message : String(e),
      values: input,
    };
  }

  revalidatePath("/");
  redirect(`/cases/${created.id}`);
}
