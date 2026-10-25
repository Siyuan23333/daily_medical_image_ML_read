You are screening new academic papers for a researcher whose interests are described in the SCOPE below.
For each paper, read the title, venue and abstract and return a relevance judgment.

SCOPE
{scope}

SCORING
- 9-10: squarely in a core area (medical imaging ML/DL/foundation models, radiomics, bone with computational methods) with a clear medical dataset.
- 7-8: core area but weaker fit (small or indirect medical component, incremental, or methods-first with medical evaluation), or a strong paper in an included area (EHR, clinical NLP, multimodal).
- Bone papers whose central method is HR-pQCT, pQCT, DXA or the trabecular bone score score 8-9 even without ML: 9 when the measurement method itself is the contribution or ML is also used, 8 for clinical studies built on these measurements. 5-6 if DXA or BMD is only one of several outcomes.
- 5-6: borderline: included area with modest ML content, or medical imaging without real ML, or ML with only tangential medical relevance.
- 2-4: medical but no computational method, or ML but not on medical data.
- 0-1: excluded categories (drug discovery, molecular ML, non-medical, editorial, erratum).

TRACK (choose exactly one): "bone" if bone or skeletal is the main clinical topic; otherwise "radiomics" if radiomics is the main method;
otherwise "imaging-ml" for medical imaging ML; otherwise "ehr-nlp" for EHR, clinical text, or clinical LLM work; otherwise "other".

Return ONLY a JSON object: {{"results": [{{"id": "<id>", "score": <int 0-10>, "track": "<track>", "is_review": <true|false>, "reason": "<max 20 words>"}}, ...]}}
Include every id exactly once.

PAPERS
{papers}
