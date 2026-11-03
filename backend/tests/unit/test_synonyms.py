"""口语 → 术语归一的单元测试（docs/05 §2.4）。"""
from app.rag.synonyms import apply_synonyms


def test_replaces_colloquial_term_with_legal_term():
    out = apply_synonyms("银行本钱不够会怎么样", append=False)
    assert "本钱" not in out
    assert "资本" in out


def test_replace_only_does_not_append_concept_terms():
    out = apply_synonyms("资本", append=False)
    assert out == "资本"


def test_append_adds_concept_terms_once():
    out = apply_synonyms("资本", append=True)
    assert "资本充足率" in out
    assert out.count("资本充足率") == 1


def test_empty_text_passthrough():
    assert apply_synonyms("") == ""


def test_plain_question_unchanged_when_nothing_matches():
    assert apply_synonyms("证券的定义是什么", append=False) == "证券的定义是什么"
