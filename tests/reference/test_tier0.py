from __future__ import annotations

from reference_runtime.tier0 import (
    Tier0Engine,
    canonical_text,
    folded_text,
    normalize,
    normalize_forms,
)


def test_canonical_preserves_vietnamese_accents_and_casefolds():
    assert canonical_text("  Xin Chào!!  ") == "xin chào"
    assert canonical_text("Hello???") == "hello"


def test_folded_strips_accents_and_is_normalize_alias():
    assert folded_text("  Xin Chào!!  ") == "xin chao"
    assert normalize("  Xin Chào!!  ") == "xin chao"
    assert normalize("Hello???") == "hello"


def test_punctuation_and_underscore_become_space():
    assert canonical_text("hello.thanks") == "hello thanks"
    assert folded_text("hello.thanks") == "hello thanks"
    assert normalize("hello.thanks") == "hello thanks"
    assert canonical_text("xin_chao") == "xin chao"
    assert folded_text("xin_chao") == "xin chao"


def test_normalize_forms_exposes_three_surfaces():
    forms = normalize_forms("Cảm ơn!!!")
    assert forms.raw == "Cảm ơn!!!"
    assert forms.canonical == "cảm ơn"
    assert forms.folded == "cam on"


def test_greeting_hits_accented_canonical():
    engine = Tier0Engine()
    decision = engine.evaluate("Xin chào")
    assert decision.hit is True
    assert decision.rule_id == "greeting"
    assert decision.matched_surface == "canonical"
    assert decision.response_text


def test_greeting_hits_unaccented_via_folded_fallback():
    engine = Tier0Engine()
    decision = engine.evaluate("chao")
    assert decision.hit is True
    assert decision.rule_id == "greeting"
    assert decision.matched_surface == "folded"


def test_chao_with_wrong_tone_does_not_hit_greeting():
    """Accent fold must not map distinct 'cháo' onto greeting 'chào'."""
    engine = Tier0Engine()
    forms = normalize_forms("cháo")
    assert forms.canonical == "cháo"
    assert forms.folded == "chao"
    assert forms.canonical != forms.folded
    decision = engine.evaluate("cháo", forms=forms)
    assert decision.hit is False


def test_greeting_hits_when_forms_passed():
    engine = Tier0Engine()
    forms = normalize_forms("XIN CHÀO!!!")
    decision = engine.evaluate("unused", forms=forms)
    assert decision.hit is True
    assert decision.rule_id == "greeting"


def test_xin_chao_with_underscore_hits_greeting():
    engine = Tier0Engine()
    decision = engine.evaluate("xin_chao")
    assert decision.hit is True
    assert decision.rule_id == "greeting"


def test_thanks_and_farewell_hit():
    engine = Tier0Engine()
    assert engine.evaluate("cam on ban").hit is True
    assert engine.evaluate("Cảm ơn bạn").hit is True
    assert engine.evaluate("Bye").hit is True


def test_broad_keyword_is_not_a_tier0_hit():
    engine = Tier0Engine()
    decision = engine.evaluate("Xin chào, tôi muốn tạo một poster cho quán cà phê")
    assert decision.hit is False


def test_live_data_question_is_not_a_tier0_hit():
    engine = Tier0Engine()
    decision = engine.evaluate("Thời tiết Hà Nội hôm nay thế nào?")
    assert decision.hit is False


def test_tier0_latency_is_recorded():
    engine = Tier0Engine()
    decision = engine.evaluate("hello")
    assert decision.latency_ms >= 0
