"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { saveEdit } from "@/lib/api";
import type { DraftContent } from "@/lib/types";

export async function saveEditAction(
  caseId: number,
  draftId: number,
  operatorVersion: DraftContent,
  rationale: string | null,
) {
  await saveEdit(draftId, operatorVersion, rationale ?? undefined);
  revalidatePath(`/cases/${caseId}/drafts/${draftId}`);
  revalidatePath(`/cases/${caseId}`);
  redirect(`/cases/${caseId}/drafts/${draftId}`);
}
