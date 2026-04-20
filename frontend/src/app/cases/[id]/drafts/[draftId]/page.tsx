import { getDraft, listDocuments } from "@/lib/api";
import DraftViewer from "@/components/DraftViewer";

export const dynamic = "force-dynamic";

export default async function DraftPage({
  params,
}: {
  params: Promise<{ id: string; draftId: string }>;
}) {
  const { id, draftId } = await params;
  const caseId = Number(id);

  const [draft, docs] = await Promise.all([
    getDraft(Number(draftId)),
    listDocuments(caseId),
  ]);

  return <DraftViewer caseId={caseId} draft={draft} documents={docs} />;
}
