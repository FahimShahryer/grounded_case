// Mirror of backend Pydantic types (narrow subset — only what the UI uses).

export type SourceSpan = {
  file: string;
  line_start: number;
  line_end: number;
  raw_text: string;
  confidence?: number;
};

export type Citation = {
  claim: string;
  spans: SourceSpan[];
};

export type FieldLine = {
  key: string;
  value: string;
};

export type DraftBlock = {
  title: string | null;
  fields: FieldLine[];
  badges: string[];
  notes: string | null;
  action_items: string[];
  citations: Citation[];
};

export type DraftSection = {
  id: string;
  heading: string;
  body: string | null;
  blocks: DraftBlock[];
  citations: Citation[];
  abstained: boolean;
};

export type DraftContent = {
  header: Record<string, string>;
  sections: DraftSection[];
};

export type Draft = {
  id: number;
  case_id: number;
  draft_type: string;
  template_version: number;
  model: string;
  content: DraftContent;
  content_markdown: string;
  parent_draft_id: number | null;
  created_at: string;
};

export type CaseOut = {
  id: number;
  case_number: string;
  borrower: string;
  property_address: string;
  county: string | null;
  state: string | null;
  servicer: string | null;
  current_status: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
};

export type OcrMeta = {
  engine: "text" | "pdfplumber" | "tesseract";
  pages?: number;
  chars?: number;
  chars_per_page?: number;
  mean_confidence?: number | null;
  rasterize_dpi?: number;
  pdfplumber_chars?: number;
  image?: boolean;
  warning?: string;
};

export type DocumentMeta = {
  ocr?: OcrMeta;
  ocr_repair?: Record<string, number>;
  [key: string]: unknown;
};

export type DocumentOut = {
  id: number;
  case_id: number;
  filename: string;
  doc_type: string;
  content_sha256: string;
  has_cleaned_text: boolean;
  meta: DocumentMeta;
  created_at: string;
};

export type DocumentDetail = DocumentOut & {
  raw_text: string;
  cleaned_text: string | null;
};

export type FactEvidenceItem = {
  document_id: number;
  document_filename: string;
  span: SourceSpan;
};

export type FactOut = {
  id: number;
  case_id: number;
  fact_type: string;
  dedup_key: string;
  payload: Record<string, unknown>;
  confidence: number;
  created_at: string;
  evidence: FactEvidenceItem[];
};

export type DraftType =
  | "title_review_summary"
  | "case_status_memo"
  | "document_checklist"
  | "action_item_extract";

export type EditOut = {
  id: number;
  draft_id: number;
  operator_id: string | null;
  operator_version: DraftContent;
  structured_diff: Record<string, unknown>;
  rationale: string | null;
  created_at: string;
};

export type PatternOut = {
  id: number;
  scope: string;
  draft_type: string | null;
  section_id: string | null;
  rule_when: string;
  rule_must: string;
  confidence: number;
  supporting_edit_ids: number[];
  version: number;
  active: boolean;
  created_at: string;
  updated_at: string;
};

export type TemplateOut = {
  id: number;
  draft_type: string;
  version: number;
  manifest: Record<string, unknown>;
  active: boolean;
  created_at: string;
};

export type MineResponse = {
  signals_collected: number;
  patterns_upserted: number;
  templates_bumped: string[];
};
