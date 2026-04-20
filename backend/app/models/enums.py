from enum import StrEnum


class DocType(StrEnum):
    title_search = "title_search"
    servicer_email = "servicer_email"
    court_order = "court_order"
    property_record = "property_record"
    other = "other"


class DraftType(StrEnum):
    title_review_summary = "title_review_summary"
    case_status_memo = "case_status_memo"
    document_checklist = "document_checklist"
    action_item_extract = "action_item_extract"


class LienType(StrEnum):
    mortgage = "mortgage"
    assignment = "assignment"
    hoa_lis_pendens = "hoa_lis_pendens"
    tax_lien = "tax_lien"
    judgment = "judgment"
    easement = "easement"
    restrictive_covenant = "restrictive_covenant"


class LienStatus(StrEnum):
    active = "active"
    assigned = "assigned"
    satisfied = "satisfied"
    unknown = "unknown"


class Priority(StrEnum):
    urgent = "urgent"
    high = "high"
    normal = "normal"
    low = "low"


class PatternScope(StrEnum):
    firm = "firm"
    operator = "operator"
    case_type = "case_type"


class EditChangeKind(StrEnum):
    fix = "fix"
    rule = "rule"
    case_specific = "case_specific"


class LlmPurpose(StrEnum):
    classify = "classify"
    ocr_repair = "ocr_repair"
    extract = "extract"
    resolve = "resolve"
    embed = "embed"
    generate = "generate"
    verify = "verify"
    diff = "diff"
    mine_pattern = "mine_pattern"
