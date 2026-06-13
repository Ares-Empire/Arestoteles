"""Configuration: env secrets, config.toml (the v1 spec), universe.yaml.

Three layers, strictly separated (CLAUDE.md guardrails #2, #6):
- Secrets come from the environment / .env only (never the repo, never prompts).
- Tunable numbers live in config.toml; `[risk]` is the enforcement layer — changing
  those values requires explicit user approval.
- The tradeable universe + source whitelist live in universe.yaml.

Everything is parsed into frozen pydantic models with `extra="forbid"` so a typo in
a config file fails the run loudly (fail closed) instead of silently using a default.
"""

import os
import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    """Secrets and machine-local values, from env / .env."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+psycopg://arestoteles:arestoteles@localhost:5432/arestoteles"
    alpaca_paper_key: str = ""
    alpaca_paper_secret: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    anthropic_api_key: str = ""
    aresium_api_token: str = ""
    edgar_user_agent: str = ""
    finnhub_api_key: str = ""  # earnings calendar (blackout rule input)

    def require(self, *names: str) -> None:
        """Fail closed if a needed secret is missing (call at point of use)."""
        missing = [n for n in names if not getattr(self, n)]
        if missing:
            raise RuntimeError(
                f"missing required env settings: {', '.join(missing)} — add them to .env"
            )


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ModeConfig(FrozenModel):
    trading_mode: Literal["paper", "live"]
    approval_mode: Literal["human_v1", "auto_exits_v2", "full_auto_v3"]
    halted: bool


class ModelsConfig(FrozenModel):
    triage: str
    analyst: str
    skeptic: str
    deep_review: str


class BudgetsConfig(FrozenModel):
    max_searches_per_day: int
    max_search_uses_per_topic: int
    max_research_topics_per_run: int
    max_api_eur_per_month: float
    max_tokens_per_run: int


class CircuitBreakersConfig(FrozenModel):
    """Drawdown tiers from NAV high-water mark (docs/05)."""

    halve_sizes_at_pct: float
    no_new_buys_at_pct: float
    full_halt_at_pct: float


class RiskConfig(FrozenModel):
    """The enforcement table (docs/05). Changes require explicit user approval."""

    max_position_pct_nav: float
    trim_threshold_pct_nav: float
    max_positions: int
    min_cash_pct: float
    max_subcluster_pct_nav: float
    min_subclusters_when_invested: int
    base_position_pct: float
    max_size_pct_by_risk_grade: dict[Literal["low", "med", "high"], float]
    max_new_capital_per_day_pct: float
    max_orders_per_day: int
    max_orders_per_week: int
    hard_stop_loss_pct: float
    review_trigger_loss_pct: float
    reentry_cooldown_trading_days: int
    earnings_blackout_days: int
    staleness_max_price_drift_pct: float
    max_order_pct_adv20: float
    limit_band_pct: float
    min_conviction_new_buy: int
    min_conviction_add: int
    conviction_cap_when_skeptic_weakened: int
    circuit_breakers: CircuitBreakersConfig


class ScheduleConfig(FrozenModel):
    morning_sweep: str
    main_run: str
    post_close: str
    weekly_review: str
    monthly_review: str
    max_event_triggered_runs_per_day: int
    no_orders_first_minutes_after_open: int


class ResearchConfig(FrozenModel):
    recency_window_days: int
    evidence_max_age_for_new_entry_days: int
    triage_threshold: int
    two_source_rule: bool


class TelegramConfig(FrozenModel):
    digest_time: str
    approval_timeout: str


class AresiumConfig(FrozenModel):
    api_bind: str


class AppConfig(FrozenModel):
    mode: ModeConfig
    models: ModelsConfig
    budgets: BudgetsConfig
    risk: RiskConfig
    schedule: ScheduleConfig
    research: ResearchConfig
    telegram: TelegramConfig
    aresium: AresiumConfig


# --- Universe ---------------------------------------------------------------

SubCluster = Literal[
    "compute-silicon",
    "networking",
    "memory",
    "analog",
    "foundry",
    "equipment",
    "eda",
    "dc-builder",
    "power-cooling",
]


class TradedName(FrozenModel):
    ticker: str
    name: str
    role: str
    subcluster: SubCluster
    note: str | None = None


class MonitoredName(FrozenModel):
    ticker: str
    signal: str


class ExcludedName(FrozenModel):
    ticker: str
    reason: str


class ValueChainMap(FrozenModel):
    demand_sources: list[str]
    flows_to: dict[str, list[str]]
    key_bottlenecks: list[str]


class ChainWalkingDiscovery(FrozenModel):
    prioritize: bool
    walk_edges: list[str]
    then: str


class UniverseConstraints(FrozenModel):
    listing: str
    min_market_cap_usd: float
    min_avg_daily_volume_usd: float


class Benchmarks(FrozenModel):
    primary: str
    secondary: list[str]


class Universe(FrozenModel):
    traded: list[TradedName]
    excluded_deliberately: list[ExcludedName]
    bench: list[str]
    monitored_only: list[MonitoredName]
    value_chain_map: ValueChainMap
    node_promotion_gate: list[str]
    chain_walking_discovery: ChainWalkingDiscovery
    benchmarks: Benchmarks
    constraints: UniverseConstraints
    search_whitelist: dict[str, list[str]]

    @property
    def traded_tickers(self) -> frozenset[str]:
        return frozenset(t.ticker for t in self.traded)

    @property
    def monitored_tickers(self) -> frozenset[str]:
        return frozenset(m.ticker for m in self.monitored_only)

    @property
    def subcluster_by_ticker(self) -> dict[str, SubCluster]:
        return {t.ticker: t.subcluster for t in self.traded}

    @property
    def all_whitelist_domains(self) -> list[str]:
        return sorted({d for group in self.search_whitelist.values() for d in group})


# --- Loaders ----------------------------------------------------------------


def _config_path() -> Path:
    override = os.environ.get("ARESTOTELES_CONFIG")
    if override:
        return Path(override)
    real = REPO_ROOT / "config" / "config.toml"
    if real.exists():
        return real
    return REPO_ROOT / "config" / "config.example.toml"


def _universe_path() -> Path:
    override = os.environ.get("ARESTOTELES_UNIVERSE")
    if override:
        return Path(override)
    return REPO_ROOT / "config" / "universe.yaml"


@lru_cache(maxsize=1)
def load_settings() -> Settings:
    return Settings()


@lru_cache(maxsize=1)
def load_config() -> AppConfig:
    path = _config_path()
    with path.open("rb") as f:
        raw = tomllib.load(f)
    # [risk.circuit_breakers] arrives nested inside [risk] from tomllib already
    return AppConfig.model_validate(raw)


@lru_cache(maxsize=1)
def load_universe() -> Universe:
    path = _universe_path()
    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return Universe.model_validate(raw)
