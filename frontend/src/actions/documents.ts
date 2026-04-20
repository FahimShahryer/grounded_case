"use server";

import { revalidatePath } from "next/cache";

type UploadResult = {
  filename: string;
  ok: boolean;
  id?: number;
  doc_type?: string;
  engine?: string;
  error?: string;
};

const BACKEND_URL = process.env.BACKEND_URL ?? "http://backend:8000";

/**
 * Server action: forward each selected file to the backend upload endpoint.
 * Runs inside the frontend container, so it uses BACKEND_URL (the compose
 * service hostname), NOT the browser-facing localhost URL.
 */
export async function uploadDocumentsAction(
  caseId: number,
  formData: FormData,
): Promise<{ results: UploadResult[] }> {
  const files = formData.getAll("files").filter((f): f is File => f instanceof File);
  if (files.length === 0) return { results: [] };

  const results: UploadResult[] = [];

  for (const file of files) {
    try {
      const body = new FormData();
      body.append("file", file, file.name);
      const res = await fetch(`${BACKEND_URL}/api/cases/${caseId}/documents`, {
        method: "POST",
        body,
      });
      if (!res.ok) {
        const errText = (await res.text()).slice(0, 300);
        results.push({
          filename: file.name,
          ok: false,
          error: `HTTP ${res.status}: ${errText}`,
        });
        continue;
      }
      const doc = (await res.json()) as {
        id: number;
        doc_type: string;
        meta?: { ocr?: { engine?: string } };
      };
      results.push({
        filename: file.name,
        ok: true,
        id: doc.id,
        doc_type: doc.doc_type,
        engine: doc.meta?.ocr?.engine,
      });
    } catch (e) {
      results.push({
        filename: file.name,
        ok: false,
        error: e instanceof Error ? e.message : String(e),
      });
    }
  }

  revalidatePath(`/cases/${caseId}`);
  return { results };
}
