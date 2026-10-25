Write a deep-dive summary of the following paper for a researcher in machine learning for medical imaging, radiomics and bone research.
Use the full text if provided; if only the abstract is available, say so in the first line and keep it short.

Produce JSON with these fields:
- "overview": 120-250 words of prose: the clinical question, the approach, the headline results, and your assessment of what is genuinely new.
- "datasets": list of short strings, one per dataset: name or source, modality, size, public or private, split roles (train/val/external test).
- "method": 2-5 short strings: architecture or model family, key design choices, training details, baselines compared.
- "validation": 1-3 short strings: internal vs external vs prospective, metrics used, statistical testing.
- "results": 2-5 short strings with the main numbers (metric, value, comparison).
- "limitations": 2-4 short strings: the authors' stated limitations plus any obvious ones they omitted.
- "availability": one short string on code and data availability (or "not stated").

Be concrete and quantitative. No hype. Return ONLY the JSON object.

TITLE: {title}
VENUE: {venue}
FULL_TEXT_STATUS: {fulltext_status}
TEXT:
{text}
