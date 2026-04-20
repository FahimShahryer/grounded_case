import { getDraft } from "@/lib/api";
import DraftEditor from "@/components/DraftEditor";

export const dynamic = "force-dynamic";

export default async function EditDraftPage({
  params,
}: {
  params: Promise<{ id: string; draftId: string }>;
}) {
  const { id, draftId } = await params;
  const caseId = Number(id);
  const draft = await getDraft(Number(draftId));
  return <DraftEditor caseId={caseId} draft={draft} />;
}
