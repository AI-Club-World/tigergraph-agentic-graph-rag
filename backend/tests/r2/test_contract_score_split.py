import json
from pathlib import Path

from ogr.r2.score import score_answer, score_set
from ogr.r2.split import make_split

ROOT = Path(__file__).resolve().parents[3]
PUBLIC = ROOT / "docs" / "round-2" / "data" / "questions_public.jsonl"


def gold():
    return {json.loads(x)["qid"]: json.loads(x) for x in PUBLIC.read_text(encoding="utf-8").splitlines()}


def sc(qid, status, answer):
    g = gold()[qid]
    return score_answer(g["status"], g["answer"], status, answer)


def test_not_in_corpus():
    assert sc("r2-pub-028", "not_in_corpus", None) == 1
    assert sc("r2-pub-028", "answered", "Someone") == 0
    assert sc("r2-pub-028", "not_in_corpus", "invented") == 0
    assert sc("r2-pub-006", "not_in_corpus", None) == 0


def test_list_of_dicts_structured_and_text():
    g = gold()["r2-pub-004"]["answer"]
    assert sc("r2-pub-004", "answered", g) == 1
    half = g[:2]
    s = sc("r2-pub-004", "answered", half)
    assert 0.5 < s < 0.8  # full precision, half recall
    extra = g + [{"year": 2020, "gold": "Nobody Atall"}]
    assert sc("r2-pub-004", "answered", extra) < 1
    text = "2012 Yi Siling; 2016 Virginia Thrasher; 2024 Ban Hyo-jin; 2028 Brooke Whitford"
    assert sc("r2-pub-004", "answered", text) == 1
    assert sc("r2-pub-004", "answered", json.dumps(g)) == 1  # JSON string


def test_dict_flat_and_rows():
    assert sc("r2-pub-006", "answered", "Japan (JPN), with 8 golds") == 1
    assert sc("r2-pub-006", "answered", {"noc": "jpn", "golds": 8.0}) == 1
    assert sc("r2-pub-006", "answered", "Japan (JPN), with 7 golds") == 0.5
    g = gold()["r2-pub-009"]["answer"]
    assert sc("r2-pub-009", "answered", g) == 1
    assert sc("r2-pub-009", "answered", {"rows": g["rows"][:4]}) < 0.9


def test_plain_string_and_int():
    assert sc("r2-pub-030", "answered", "The director was ron howard.") == 1
    assert sc("r2-pub-030", "answered", "Steven Spielberg") == 0
    assert sc("r2-pub-038", "answered", "22 documents") == 1
    assert sc("r2-pub-038", "answered", "twenty-two") == 0  # number words only go to twenty


def test_partial_found_not_in_corpus():
    g = gold()["r2-pub-029"]["answer"]
    assert sc("r2-pub-029", "partial", g) == 1
    assert sc("r2-pub-029", "answered", g) == 0.5
    assert sc("r2-pub-029", "partial", "2004 Keiji Suzuki, 2012 and 2016 Teddy Riner; 2008 is not in the corpus") == 1


def test_yes_no_explanations():
    assert sc("r2-pub-041", "answered", "No. The signed jury decision of 23 July at 22:15 PDT supersedes it.") > 0.4
    assert sc("r2-pub-041", "answered", "Yes, it is the final result of 23 July 22:15 PDT.") < \
        sc("r2-pub-041", "answered", "No. The signed jury decision of 23 July at 22:15 PDT supersedes it.")
    assert sc("r2-pub-050", "answered", "No, absence of a log entry does not prove it; both estimates are unverified.") > 0
    assert sc("r2-pub-023", "answered", "Lyles won by 5 milliseconds: 9.784 vs 9.789") == 1
    assert sc("r2-pub-023", "answered", "Kerley won clearly") == 0


def test_claims_dict_soft_match():
    g = gold()["r2-pub-048"]["answer"]
    assert sc("r2-pub-048", "partial", g) == 1
    assert sc("r2-pub-048", "partial", "A spectator said an 11-minute pause (unverified); a volunteer said 14-minute "
              "pause (unverified); nothing is verified.") > 0.5


def test_score_set_mean_and_missing():
    rows = [json.loads(x) for x in PUBLIC.read_text(encoding="utf-8").splitlines()]
    preds = [{"qid": r["qid"], "status": r["status"], "answer": r["answer"]} for r in rows]
    assert score_set(rows, preds)["accuracy_pct"] == 100.0
    assert score_set(rows, preds[:25])["accuracy_pct"] < 60
    assert score_set(rows, [])["accuracy_pct"] == 0.0


def test_split_sizes_and_stability():
    rows = list(gold().values())
    a = make_split(rows)
    assert a == make_split(list(reversed(rows)))
    n_check = list(a.values()).count("check")
    assert len(a) == 50 and 10 <= n_check <= 18
    assert json.loads((ROOT / "docs" / "round-2" / "data" / "public_split.json").read_text()) == a
