import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from daily_read.config import load_config
from daily_read.models import Paper, normalize_doi, normalize_title
from daily_read.dedup import merge_duplicates
from daily_read.prefilter import Prefilter
from daily_read.state import State
from daily_read.sources.pubmed import parse_pubmed_xml
from daily_read.fulltext.europepmc import jats_to_text
from daily_read import render


def cfg():
    return load_config()


def test_normalize():
    assert normalize_doi("https://doi.org/10.1038/S41591-026-04730-X") == "10.1038/s41591-026-04730-x"
    assert normalize_title("  Deep-Learning <i>for</i> Bone!! ") == "deep learning for bone"


def test_key_priority():
    p = Paper(title="X", doi="10.1/abc", arxiv_id="2510.00001v2")
    assert p.key == "doi:10.1/abc"
    assert Paper(title="X", arxiv_id="2510.00001v2").key == "arxiv:2510.00001"
    assert Paper(title="Same title here").key == Paper(title="same TITLE here").key


def test_merge_preprint_and_journal():
    a = Paper(title="Foundation models for bone age estimation", arxiv_id="2510.1", authors=["Jane Doe", "A B"], venue="arXiv", venue_type="preprint", source="arxiv", abstract="short")
    j = Paper(title="Foundation Models for Bone Age Estimation", doi="10.1/x", authors=["J Doe"], venue="Radiology", venue_type="journal", source="pubmed", journal_list=True, journal_tier=1, abstract="a much longer abstract " * 5)
    out = merge_duplicates([a, j])
    assert len(out) == 1
    m = out[0]
    assert m.venue == "Radiology" and m.arxiv_id == "2510.1" and m.doi == "10.1/x" and m.journal_list


def test_prefilter_rules():
    pf = Prefilter(cfg())
    ok, _ = pf.check(Paper(title="Motor compound fault diagnosis with attention", abstract="We diagnose induction motor faults.", source="arxiv"))
    assert not ok
    ok, _ = pf.check(Paper(title="Opportunistic osteoporosis screening from routine CT with deep learning", abstract="Patients ...", source="arxiv"))
    assert ok
    ok, _ = pf.check(Paper(title="Erratum: something", abstract="", source="pubmed", journal_list=True))
    assert not ok
    ok, _ = pf.check(Paper(title="A trial of denosumab in postmenopausal women", abstract="randomized", source="pubmed", journal_list=True))
    assert ok  # journal-list papers skip the keyword prefilter; the LLM decides
    ok, _ = pf.check(Paper(title="EEG biomarkers of Rett syndrome", abstract="no computational method", source="medrxiv"))
    assert not ok
    ok, why = pf.check(Paper(title="Bone microarchitecture by HR-pQCT in type 1 diabetes", abstract="cross-sectional cohort", source="medrxiv"))
    assert ok and "densitometry" in why  # HR-pQCT/DXA preprints pass without an ML term


def test_state_roundtrip(tmp_path):
    st = State(tmp_path / "t.sqlite")
    p = Paper(title="T", doi="10.1/t", venue="Bone", source="crossref", visible_date="2026-10-20")
    st.upsert(p, "pending_abstract")
    assert st.known_keys([p.key])[p.key]["status"] == "pending_abstract"
    st.upsert(p, "scored", score=8, track="bone", is_review=0, reason="r", digest_date="2026-10-20")
    row = st.known_keys([p.key])[p.key]
    assert row["score"] == 8 and row["status"] == "scored"
    assert st.last_success() is None
    rid = st.start_run(__import__("datetime").datetime(2026, 10, 25), __import__("datetime").datetime(2026, 10, 25), False)
    st.finish_run(rid, "ok", {"a": 1})
    assert st.last_success() is not None
    st.save_report("2026-10-24", n_papers=1, counts={"bone": 1}, html_path="x", md_path="y", url="u", headline="h", note="")
    assert st.latest_report_date() == "2026-10-24"


PUBMED_XML = b"""<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>1</PMID><Article>
<Journal><ISSN IssnType="Electronic">1523-4681</ISSN><Title>Journal of bone and mineral research</Title><JournalIssue><PubDate><Year>2026</Year><Month>Oct</Month><Day>20</Day></PubDate></JournalIssue></Journal>
<ArticleTitle>Deep learning on DXA.</ArticleTitle><Abstract><AbstractText Label="BACKGROUND">B.</AbstractText><AbstractText Label="RESULTS">R.</AbstractText></Abstract>
<AuthorList><Author><LastName>Doe</LastName><Initials>J</Initials></Author></AuthorList><PublicationTypeList><PublicationType>Journal Article</PublicationType></PublicationTypeList>
</Article><MedlineJournalInfo><ISSNLinking>0884-0431</ISSNLinking></MedlineJournalInfo></MedlineCitation>
<PubmedData><History><PubMedPubDate PubStatus="entrez"><Year>2026</Year><Month>10</Month><Day>22</Day></PubMedPubDate></History>
<ArticleIdList><ArticleId IdType="doi">10.1093/jbmr/zjaf001</ArticleId><ArticleId IdType="pmc">PMC123</ArticleId></ArticleIdList></PubmedData></PubmedArticle></PubmedArticleSet>"""


def test_pubmed_parse():
    ps = parse_pubmed_xml(PUBMED_XML, cfg())
    assert len(ps) == 1
    p = ps[0]
    assert p.journal_list and p.venue == "JBMR" and p.doi == "10.1093/jbmr/zjaf001"
    assert p.visible_date == "2026-10-22" and p.published == "2026-10-20"
    assert p.abstract.startswith("BACKGROUND: B.") and p.authors == ["J Doe"] and p.pmcid == "PMC123"


def test_jats_to_text():
    xml = b"<article><body><sec><title>Methods</title><p>" + b"word " * 200 + b"</p></sec></body></article>"
    t = jats_to_text(xml)
    assert t and t.startswith("\n## Methods")


def test_render_day(tmp_path):
    c = cfg()
    p = Paper(title="Radiomics of hip fractures", doi="10.1/r", venue="European Radiology", source="springer", published="2026-10-23", authors=["A One", "B Two", "C Three", "D Four"])
    row = dict(record=p.to_json(), track="bone", score=9, is_review=0, late_of=None, summary="S1. S2.", deepdive=json.dumps({"overview": "O", "datasets": ["d"], "method": [], "validation": [], "results": ["r"], "limitations": [], "availability": "code on GitHub"}), fulltext_status="oa:unpaywall-pdf", title=p.title, venue=p.venue, key=p.key)
    out = render.render_day(c, "2026-10-23", [row], "Headline.", "", [], "w")
    assert "Radiomics of hip fractures" in out["html"] and "Deep dive" in out["html"] and "et al." in out["html"]
    assert out["counts"] == {"bone": 1} and out["deepdives"][0]["one_liner"] == "S1."
    assert "## Bone and skeletal" in out["md"]
    assert out["n_curated"] == 0 and 'class="pill"' not in out["html"] and 'id="only-curated"' not in out["html"]
    # a curated-journal paper with a lower score is listed first in its track and carries the marker everywhere
    q = Paper(title="Bone density from JBMR", doi="10.1/q", venue="JBMR", source="pubmed", journal_list=True, journal_tier=1, published="2026-10-23")
    row2 = dict(row, record=q.to_json(), score=7, deepdive=None, fulltext_status=None, title=q.title, venue=q.venue, key=q.key)
    out = render.render_day(c, "2026-10-23", [row, row2], "Headline.", "", [], "w")
    html, md = out["html"], out["md"]
    assert out["n_curated"] == 1 and "from your journal list" in html and 'id="only-curated"' in html
    assert html.index("Bone density from JBMR") < html.index("Radiomics of hip fractures")
    assert '<tr class="curated">' in html and 'class="curated"' in html and html.count('class="pill"') == 2
    assert "- ★ Bone density from JBMR" in md and "### ★ Bone density from JBMR" in md and "★ Radiomics" not in md
    em = render.render_email(c, "2026-10-23", "http://x", 2, "H", out["deepdives"], [], n_curated=1)
    assert "1 from your journal list" in em["text"]


def test_source_class_thresholds_and_impact_cut():
    from daily_read.pipeline import impact_ok, load_thresholds, SOURCE_CLASSES
    j = Paper(title="J", doi="10.1/j", venue="Bone", source="pubmed", journal_list=True)
    q = Paper(title="Q", pmid="1", venue="The Knee", source="pubmed", extra={"pubmed_hit": "bone_ml"})
    a = Paper(title="A", arxiv_id="2510.1", venue="arXiv", venue_type="preprint", source="arxiv")
    assert (j.source_class, q.source_class, a.source_class) == ("curated", "pubmed_query", "preprint")
    th = load_thresholds(cfg())
    assert set(th) == set(SOURCE_CLASSES) and th["curated"] <= th["pubmed_query"]
    assert load_thresholds(cfg(), 5) == {c: 5 for c in SOURCE_CLASSES}
    q.extra["impact"] = {"value": 1.4}
    assert not impact_ok(q, 2) and impact_ok(q, 0)
    q.extra["impact"] = None
    assert impact_ok(q, 2)                      # unknown impact factor is kept
    a.extra["impact"] = {"value": 0.1}
    assert impact_ok(a, 2)                      # preprints are never cut
    j.extra["impact"] = {"value": 3.5}
    assert impact_ok(j, 2)


def test_clean_journal_title():
    from daily_read.sources.pubmed import clean_journal_title as c
    assert c("Osteoporosis international : a journal established as result of cooperation between the European Foundation for Osteoporosis and the National Osteoporosis Foundation of the USA", "Osteoporos Int") == "Osteoporosis International"
    assert c("Journal of medical imaging (Bellingham, Wash.)") == "Journal of Medical Imaging"
    assert c("Medical & biological engineering & computing") == "Medical & Biological Engineering & Computing"
    assert c("CNS neuroscience & therapeutics") == "CNS Neuroscience & Therapeutics"
    assert c("npj precision oncology") == "npj Precision Oncology"
    assert c("The Lancet. Digital health") == "The Lancet. Digital Health"
    assert c("Spectrochimica acta. Part A, Molecular and biomolecular spectroscopy that goes on and on and on", "Spectrochim Acta A") == "Spectrochim Acta A"
    assert c("Radiology") == "Radiology"


def test_personal_values_come_from_env(monkeypatch):
    monkeypatch.setenv("CONTACT_EMAIL", "x@example.org")
    monkeypatch.setenv("DIGEST_EMAIL_TO", "a@example.org, b@example.org")
    monkeypatch.setenv("DIGEST_EMAIL_FROM", "a@example.org")
    c = load_config()
    assert c.settings["fulltext"]["unpaywall_email"] == "x@example.org" and c.settings["fulltext"]["crossref_mailto"] == "x@example.org"
    assert c.settings["email"]["to"] == ["a@example.org", "b@example.org"] and c.settings["email"]["from"] == "a@example.org"
    from daily_read.util import user_agent
    assert "mailto:x@example.org" in user_agent()


def test_assign_days():
    from datetime import date
    from daily_read.pipeline import assign_days
    D = date
    # ordinary morning: one day, yesterday
    plan, late, trunc = assign_days([("a", D(2026, 10, 24)), ("b", D(2026, 10, 25))], D(2026, 10, 24), D(2026, 10, 24), 7)
    assert plan == {"2026-10-24": ["a"]} and late == {} and not trunc      # b is dated after the horizon and waits
    # catch-up capped at 3 days: older papers become late arrivals in the newest day
    plan, late, trunc = assign_days([("old", D(2026, 10, 18)), ("c", D(2026, 10, 23))], D(2026, 10, 18), D(2026, 10, 24), 3)
    assert sorted(plan) == ["2026-10-22", "2026-10-23", "2026-10-24"] and plan["2026-10-24"] == ["old"] and late == {"old": "2026-10-18"} and trunc
    # a report for the horizon day already exists (first_open is past it): same-day papers extend it, older ones are late
    plan, late, _ = assign_days([("x", D(2026, 10, 25)), ("y", D(2026, 10, 24))], D(2026, 10, 26), D(2026, 10, 25), 7)
    assert plan == {"2026-10-25": ["x", "y"]} and late == {"y": "2026-10-24"}


def test_per_query_threshold():
    from daily_read.pipeline import threshold_for
    th, qth = {"curated": 7, "pubmed_query": 9, "preprint": 9}, {"hrpqct_dxa": 8}
    both = Paper(title="B", pmid="2", source="pubmed", extra={"pubmed_hit": "bone_ml", "pubmed_hits": ["bone_ml", "hrpqct_dxa"]})
    only = Paper(title="R", pmid="3", source="pubmed", extra={"pubmed_hit": "radiomics", "pubmed_hits": ["radiomics"]})
    legacy = Paper(title="L", pmid="4", source="pubmed", extra={"pubmed_hit": "hrpqct_dxa"})
    cur = Paper(title="C", doi="10.1/c", source="pubmed", journal_list=True, extra={"pubmed_hit": "journal"})
    assert threshold_for(both, th, qth) == 8          # lowest override among matching queries
    assert threshold_for(only, th, qth) == 9
    assert threshold_for(legacy, th, qth) == 8        # records without pubmed_hits still work
    assert threshold_for(cur, th, qth) == 7
    assert threshold_for(both, th, {}) == 9           # --threshold override clears per-query values
