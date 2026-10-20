from pathlib import Path

import yaml

from tenderwatch.filtering import Scorer
from tenderwatch.models import Tender

CFG = yaml.safe_load((Path(__file__).resolve().parent.parent / "config.yaml").read_text())["keywords"]
S = Scorer(CFG)


def t(title, desc="", cat=""):
    return Tender(source="x", source_id="1", title=title, description=desc, category=cat)


def test_clear_ai_tender_is_relevant():
    x = t("Consultancy for AI-based chatbot and machine learning model")
    assert S.evaluate(x)
    assert x.score >= 6


def test_acronym_does_not_match_inside_words():
    assert not S.evaluate(t("Supply of air conditioners and mail servers"))
    assert not S.evaluate(t("Repair of main building and maintain facility"))


def test_data_and_digital_terms():
    assert S.evaluate(t("Development of a data warehouse and business intelligence dashboards"))
    assert S.evaluate(t("Digital transformation roadmap for the department"))


def test_single_weak_term_is_not_enough():
    assert not S.evaluate(t("Training workshop and capacity building"))


def test_exclusion_drops_borderline_but_not_strong():
    assert not S.evaluate(t("Supply of printing of stationery and automation of forms"))
    strong = t("AI machine learning platform with data analytics, supply of stationery for the project")
    assert S.evaluate(strong)


def test_hits_per_group_are_capped():
    x = t("AI machine learning deep learning generative AI LLM chatbot")
    S.evaluate(x)
    assert x.score == 5 * 2  # max two hits count for the ai group


def test_buyer_name_is_not_scored():
    x = Tender(source="x", source_id="2", title="Supply of stationery", buyer="Pakistan Digital Authority")
    assert not S.evaluate(x)


def test_ampersand_glues_acronym():
    from tenderwatch.filtering import Scorer
    s = Scorer({"groups": {"ai": {"weight": 5, "terms": ["AI"]}}})
    assert s.score_text("RENOVATION FOR H&AI FAISALABAD ZONE")[0] == 0
    assert s.score_text("Use of AI in tax")[0] == 5
