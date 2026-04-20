"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { createDraft, runProcess } from "@/lib/api";
import type { DraftType } from "@/lib/types";

export async function generateDraftAction(formData: FormData) {
  const caseId = Number(formData.get("case_id"));
  const draftType = formData.get("draft_type") as DraftType;
  if (!caseId || !draftType) {
    throw new Error("Missing case_id or draft_type");
  }
  const draft = await createDraft(caseId, draftType);
  revalidatePath(`/cases/${caseId}`);
  redirect(`/cases/${caseId}/drafts/${draft.id}`);
}

export async function runProcessAction(formData: FormData) {
  const caseId = Number(formData.get("case_id"));
  if (!caseId) throw new Error("Missing case_id");
  await runProcess(caseId);
  revalidatePath(`/cases/${caseId}`);
}
