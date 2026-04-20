"""The improvement loop: turn operator edits into durable patterns.

Pipeline:
    diff_drafts(system, operator)  →  EditDiff
    classify_changes(diff)          →  list[ClassifiedChange]  (fix | rule | case-specific)
    mine_patterns(signals)          →  list[MinedPattern]       (generalized rules)
    upsert_pattern(...)             →  persisted row + reinforcement
    update_template(draft_type)     →  new active Template referencing patterns
"""
