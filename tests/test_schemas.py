"""Schema-level discipline: malformed or undisciplined AI output must not validate
(docs/04 — unfalsifiable theses and untraceable chains are rejected before the
risk engine ever sees them)."""

import pytest
from pydantic import ValidationError

from arestoteles.schemas import DecisionDraft, Falsifier

FALSIFIER = Falsifier(id="F1", text="Any top-3 hyperscaler cuts FY26 capex guidance")
DISCIPLINE = dict(
    chain="MSFT capex raise -> dc buildout -> power demand -> VRT",
    priced_in_check="VRT moved 1.5%; EV/S still inside its 1-year band.",
    falsifiers=(FALSIFIER,),
    evidence_ids=(7,),
)


def test_buy_requires_full_discipline():
    DecisionDraft(
        ticker="vrt",
        action="buy",
        conviction=75,
        risk_grade="med",
        rationale="Downstream beneficiary.",
        **DISCIPLINE,
    )


@pytest.mark.parametrize("missing", ["chain", "priced_in_check", "falsifiers", "evidence_ids"])
def test_buy_missing_any_discipline_field_fails(missing):
    kw = dict(DISCIPLINE)
    kw[missing] = "" if missing in ("chain", "priced_in_check") else ()
    with pytest.raises(ValidationError, match=missing.replace("_", " ").split()[0]):
        DecisionDraft(
            ticker="VRT",
            action="buy",
            conviction=75,
            risk_grade="med",
            rationale="x",
            **kw,
        )


def test_hold_and_exit_need_no_discipline_fields():
    DecisionDraft(
        ticker="VRT", action="hold", conviction=50, risk_grade="med", rationale="No new evidence."
    )
    DecisionDraft(
        ticker="VRT",
        action="exit",
        conviction=0,
        risk_grade="high",
        rationale="Falsifier F2 triggered.",
    )


def test_ticker_normalized_and_conviction_bounded():
    d = DecisionDraft(ticker=" nvda ", action="hold", conviction=0, risk_grade="low", rationale="x")
    assert d.ticker == "NVDA"
    with pytest.raises(ValidationError):
        DecisionDraft(ticker="NVDA", action="hold", conviction=101, risk_grade="low", rationale="x")
    with pytest.raises(ValidationError):
        DecisionDraft(ticker="NVDA", action="bye", conviction=50, risk_grade="low", rationale="x")  # type: ignore[arg-type]


def test_falsifier_must_be_substantive():
    with pytest.raises(ValidationError):
        Falsifier(id="F1", text="bad vibes")
