"""Pydantic contracts for everything the AI emits (CLAUDE.md guardrail #1: the AI
outputs DecisionDraft JSON only; code does everything else).

Schema-level rejections are part of the risk design (docs/04): unfalsifiable theses,
untraceable chains, and missing priced-in checks fail validation before the risk
engine even sees them. Malformed output ⇒ the stage fails closed.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Action = Literal["buy", "add", "trim", "exit", "hold"]
RiskGrade = Literal["low", "med", "high"]
SkepticVerdict = Literal["ok", "weakened", "factual_error"]


class Falsifier(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1)  # F1, F2, ...
    text: str = Field(min_length=10)


class DecisionDraft(BaseModel):
    """One proposed action from the analyst pass (docs/04 Layer 5)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ticker: str = Field(min_length=1, max_length=8)
    action: Action
    conviction: int = Field(ge=0, le=100)
    risk_grade: RiskGrade
    horizon_days: int | None = Field(default=None, gt=0)
    target_weight_pct: float | None = Field(default=None, ge=0, le=100)
    # The explicit causal path through the value-chain graph, each hop backed by an
    # evidence id or a graph edge ("MSFT capex raise -> dc buildout -> power -> VRT").
    chain: str = ""
    # How much of the thesis is already in the price, and why edge remains.
    priced_in_check: str = ""
    thesis_update: str = ""
    falsifiers: tuple[Falsifier, ...] = ()
    evidence_ids: tuple[int, ...] = ()
    rationale: str = Field(min_length=1)

    @field_validator("ticker")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.strip().upper()

    @model_validator(mode="after")
    def _capital_deployment_needs_discipline(self) -> "DecisionDraft":
        """buy/add must carry the full evidence discipline; exits stay easy
        (the gate guards capital deployment, never capital return — docs/05)."""
        if self.action in ("buy", "add"):
            problems = []
            if len(self.chain.strip()) < 10:
                problems.append("chain (causal path) is required for buy/add")
            if len(self.priced_in_check.strip()) < 10:
                problems.append("priced_in_check is required for buy/add")
            if not self.falsifiers:
                problems.append("falsifiers are required for buy/add (unfalsifiable = rejected)")
            if not self.evidence_ids:
                problems.append("evidence_ids are required for buy/add")
            if problems:
                raise ValueError("; ".join(problems))
        return self


class SkepticReview(BaseModel):
    """Adversarial second pass over a non-HOLD draft (docs/04 Layer 6)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    verdict: SkepticVerdict
    notes: str = ""


class EvidenceItem(BaseModel):
    """One entry of an evidence pack (docs/04 Layer 4). Numbers for decisions never
    come from these — only qualitative facts; prices/fundamentals come from APIs."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ticker: str
    claim: str = Field(min_length=1)
    exact_quote: str = Field(min_length=1)
    url: str = Field(min_length=1)
    publisher: str = Field(min_length=1)
    published_at: str  # ISO date from the source; parsed/checked by code
    relevance: str = ""
