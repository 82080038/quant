"""Trading Automation Orchestrator (pustaka/32, 40, 67, 76, 83, 93).

Mengelola otomatisasi eksekusi hasil keputusan/sinyal trading berdasarkan
screening AI/ML/model/engine. Sebelum eksekusi otomatis dijalankan,
AutomationGate memeriksa semua aturan kelayakan.

Komponen:
- AutomationConfig: konfigurasi otomatisasi (centang pilihan user).
- AutomationGate: aturan kapan boleh dicentang / tidak boleh.
- ExecutionPlan: rencana eksekusi dari hasil screening ke order.
- AutoExecutor: eksekutor yang menjalankan plan via broker adapter.
- AutomationOrchestrator: menyatukan gate → plan → execute.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from quant.config import settings
from quant.risk.engine import CircuitBreaker, DailyLossTracker
from quant.risk.leverage import LeverageConfig

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class SignalSource(Enum):
    """Sumber sinyal trading yang dapat diotomatisasi."""

    SCREENING_AI = "screening_ai"
    MODEL_PREDICTION = "model_prediction"
    ADVISORY_RECOMMENDATION = "advisory_recommendation"
    PATTERN_SIGNAL = "pattern_signal"
    BACKTEST_SIGNAL = "backtest_signal"
    WALK_FORWARD_SIGNAL = "walk_forward_signal"


class MarketScope(Enum):
    """Cakupan pasar untuk portofolio otomatis."""

    IDX = "idx"
    GLOBAL = "global"
    MULTI_ASSET = "multi_asset"


class ExecutionMode(Enum):
    """Mode eksekusi."""

    MANUAL = "manual"
    SEMI_AUTO = "semi_auto"
    FULL_AUTO = "full_auto"


class GateCheckStatus(Enum):
    """Status hasil pemeriksaan gate."""

    PASS = "pass"
    FAIL = "fail"
    WARNING = "warning"


class PlanStatus(Enum):
    """Status rencana eksekusi."""

    DRAFT = "draft"
    VALIDATED = "validated"
    REJECTED = "rejected"
    EXECUTING = "executing"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


# ---------------------------------------------------------------------------
# Automation Config
# ---------------------------------------------------------------------------


@dataclass
class AutomationConfig:
    """Konfigurasi otomatisasi yang dipilih user via centang.

    Setiap field mewakili satu centang di FE. Aturan kapan boleh dicentang
    dan kapan tidak diatur oleh AutomationGate.
    """

    # Sinyal yang boleh dieksekusi otomatis
    enabled_sources: set[SignalSource] = field(default_factory=set)

    # Cakupan pasar
    market_scope: set[MarketScope] = field(default_factory=set)

    # Mode eksekusi
    execution_mode: ExecutionMode = ExecutionMode.MANUAL

    # Tingkat kepercayaan minimum untuk auto-eksekusi (0-100)
    min_confidence: float = 65.0

    # Maksimum jumlah order per sesi
    max_orders_per_session: int = 5

    # Maksimum nilai eksekusi per sesi (IDR)
    max_value_per_session: float = 50_000_000

    # Apakah sell/exit juga dieksekusi otomatis
    auto_sell: bool = False

    # Apakah re-balancing otomatis diaktifkan
    auto_rebalance: bool = False

    # Leverage config (toggle user)
    leverage_config: LeverageConfig = field(default_factory=LeverageConfig)

    # Konfirmasi user (harus dicentang sebelum live)
    confirmed_paper_30d: bool = False
    confirmed_risk_understood: bool = False
    confirmed_risk_limits: bool = False

    # Timestamp konfigurasi
    configured_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat(),
    )

    def is_any_enabled(self) -> bool:
        """Apakah ada otomatisasi yang diaktifkan."""
        return bool(self.enabled_sources) and self.execution_mode != ExecutionMode.MANUAL

    def is_live_ready(self) -> bool:
        """Apakah semua konfirmasi live sudah dicentang."""
        return (
            self.confirmed_paper_30d
            and self.confirmed_risk_understood
            and self.confirmed_risk_limits
        )


# ---------------------------------------------------------------------------
# Gate Check Result
# ---------------------------------------------------------------------------


@dataclass
class GateRule:
    """Satu aturan gate dengan hasil pemeriksaan."""

    rule_id: str
    description: str
    status: GateCheckStatus
    detail: str = ""
    is_blocking: bool = True


@dataclass
class GateResult:
    """Hasil pemeriksaan semua aturan gate."""

    passed: bool
    rules: list[GateRule] = field(default_factory=list)
    blocking_count: int = 0
    warning_count: int = 0
    summary: str = ""

    @property
    def can_proceed(self) -> bool:
        return self.passed and self.blocking_count == 0


# ---------------------------------------------------------------------------
# Automation Gate
# ---------------------------------------------------------------------------


class AutomationGate:
    """Aturan kapan otomatisasi boleh dicentang dan kapan tidak.

    Memeriksa:
    1. Environment (research/paper/live)
    2. Approval token untuk live
    3. Konfirmasi user (paper 30 hari, risiko, limit)
    4. Readiness gate per instrumen
    5. Circuit breaker
    6. Status pasar (jam trading)
    7. Performa model (tidak degraded)
    8. Risk limits
    9. Market scope (IDX vs global)
    """

    def __init__(
        self,
        env: str | None = None,
        live_approved: bool | None = None,
        circuit_breaker_triggered: bool = False,
        market_open: bool = True,
        model_degraded: bool = False,
        paper_trading_days: int = 0,
        daily_loss_halted: bool = False,
    ) -> None:
        self.env = env or settings.env
        self.live_approved = live_approved if live_approved is not None else settings.live_approved
        self.circuit_breaker_triggered = circuit_breaker_triggered
        self.market_open = market_open
        self.model_degraded = model_degraded
        self.paper_trading_days = paper_trading_days
        self.daily_loss_halted = daily_loss_halted

    @classmethod
    def from_circuit_breaker(
        cls,
        cb: CircuitBreaker,
        env: str | None = None,
        live_approved: bool | None = None,
        market_open: bool = True,
        model_degraded: bool = False,
        paper_trading_days: int = 0,
        daily_loss_tracker: DailyLossTracker | None = None,
    ) -> AutomationGate:
        """Construct gate with circuit breaker and daily loss state auto-wired.

        Args:
            cb: CircuitBreaker instance (from risk.engine).
            env: Environment override.
            live_approved: Live approval override.
            market_open: Market open status.
            model_degraded: Model degradation flag.
            paper_trading_days: Days of paper trading completed.
            daily_loss_tracker: Optional DailyLossTracker for daily loss limit.

        Returns:
            AutomationGate with circuit_breaker_triggered and daily_loss_halted set.
        """
        return cls(
            env=env,
            live_approved=live_approved,
            circuit_breaker_triggered=cb.is_triggered,
            market_open=market_open,
            model_degraded=model_degraded,
            paper_trading_days=paper_trading_days,
            daily_loss_halted=daily_loss_tracker.is_halted if daily_loss_tracker else False,
        )

    def update_circuit_breaker(self, cb: CircuitBreaker) -> None:
        """Live-update circuit breaker state from a CircuitBreaker instance.

        Call this before check_config() or execute() to ensure the gate
        reflects the latest drawdown state.

        Args:
            cb: CircuitBreaker instance with current state.
        """
        self.circuit_breaker_triggered = cb.is_triggered

    def update_daily_loss(self, tracker: DailyLossTracker) -> None:
        """Live-update daily loss halt state from a DailyLossTracker instance.

        Call this before check_config() or execute() to ensure the gate
        reflects the latest daily P&L state.

        Args:
            tracker: DailyLossTracker instance with current state.
        """
        self.daily_loss_halted = tracker.is_halted

    def check_config(self, config: AutomationConfig) -> GateResult:
        """Periksa apakah konfigurasi otomatisasi boleh diaktifkan.

        Args:
            config: Konfigurasi yang dipilih user.

        Returns:
            GateResult dengan daftar aturan dan status.
        """
        rules: list[GateRule] = []

        # R1: Environment check
        if config.execution_mode == ExecutionMode.FULL_AUTO and self.env == "research":
            rules.append(GateRule(
                rule_id="R1_ENV",
                description="Environment harus paper atau live untuk auto-eksekusi",
                status=GateCheckStatus.FAIL,
                detail=f"Env saat ini: {self.env}. FULL_AUTO tidak diizinkan di research.",
            ))
        else:
            rules.append(GateRule(
                rule_id="R1_ENV",
                description="Environment sesuai untuk mode eksekusi",
                status=GateCheckStatus.PASS,
                detail=f"Env: {self.env}, mode: {config.execution_mode.value}",
            ))

        # R2: Live approval
        if self.env == "live":
            if not self.live_approved:
                rules.append(GateRule(
                    rule_id="R2_LIVE_APPROVAL",
                    description="Approval token untuk live trading harus ada",
                    status=GateCheckStatus.FAIL,
                    detail="Live approval token belum disetujui. "
                           "Buat file approval.token manual.",
                ))
            else:
                rules.append(GateRule(
                    rule_id="R2_LIVE_APPROVAL",
                    description="Approval token live trading tersedia",
                    status=GateCheckStatus.PASS,
                ))
        else:
            rules.append(GateRule(
                rule_id="R2_LIVE_APPROVAL",
                description="Approval token tidak diperlukan (non-live)",
                status=GateCheckStatus.PASS,
                detail=f"Env: {self.env}",
            ))

        # R3: Konfirmasi user
        if config.execution_mode != ExecutionMode.MANUAL:
            missing = []
            if not config.confirmed_paper_30d:
                missing.append("Paper trading 30 hari")
            if not config.confirmed_risk_understood:
                missing.append("Pemahaman risiko")
            if not config.confirmed_risk_limits:
                missing.append("Risk limits disetujui")

            if missing:
                rules.append(GateRule(
                    rule_id="R3_CONFIRMATIONS",
                    description="Semua konfirmasi user harus dicentang",
                    status=GateCheckStatus.FAIL,
                    detail=f"Belum dicentang: {', '.join(missing)}",
                ))
            else:
                rules.append(GateRule(
                    rule_id="R3_CONFIRMATIONS",
                    description="Semua konfirmasi user telah dicentang",
                    status=GateCheckStatus.PASS,
                ))
        else:
            rules.append(GateRule(
                rule_id="R3_CONFIRMATIONS",
                description="Konfirmasi tidak diperlukan (mode manual)",
                status=GateCheckStatus.PASS,
            ))

        # R4: Paper trading minimum 30 hari untuk live
        if self.env == "live" and config.execution_mode != ExecutionMode.MANUAL:
            if self.paper_trading_days < 30:
                rules.append(GateRule(
                    rule_id="R4_PAPER_30D",
                    description="Paper trading minimal 30 hari sebelum live",
                    status=GateCheckStatus.FAIL,
                    detail=f"Paper trading baru {self.paper_trading_days} hari.",
                ))
            else:
                rules.append(GateRule(
                    rule_id="R4_PAPER_30D",
                    description=f"Paper trading {self.paper_trading_days} hari (>= 30)",
                    status=GateCheckStatus.PASS,
                ))
        else:
            rules.append(GateRule(
                rule_id="R4_PAPER_30D",
                description="Tidak diperlukan (non-live atau manual)",
                status=GateCheckStatus.PASS,
            ))

        # R5: Circuit breaker
        if self.circuit_breaker_triggered:
            rules.append(GateRule(
                rule_id="R5_CIRCUIT_BREAKER",
                description="Circuit breaker tidak boleh triggered",
                status=GateCheckStatus.FAIL,
                detail="Circuit breaker aktif — semua auto-eksekusi dihentikan.",
            ))
        else:
            rules.append(GateRule(
                rule_id="R5_CIRCUIT_BREAKER",
                description="Circuit breaker tidak triggered",
                status=GateCheckStatus.PASS,
            ))

        # R12: Daily loss limit
        if self.daily_loss_halted:
            rules.append(GateRule(
                rule_id="R12_DAILY_LOSS",
                description="Daily loss limit tidak boleh tercapai",
                status=GateCheckStatus.FAIL,
                detail="Daily loss limit tercapai — semua auto-eksekusi dihentikan untuk hari ini.",
            ))
        else:
            rules.append(GateRule(
                rule_id="R12_DAILY_LOSS",
                description="Daily loss limit belum tercapai",
                status=GateCheckStatus.PASS,
            ))

        # R6: Market open
        if config.execution_mode == ExecutionMode.FULL_AUTO and not self.market_open:
            rules.append(GateRule(
                rule_id="R6_MARKET_OPEN",
                description="Pasar harus buka untuk FULL_AUTO",
                status=GateCheckStatus.FAIL,
                detail="Pasar tutup — FULL_AUTO tidak dapat berjalan.",
                is_blocking=False,
            ))
        else:
            rules.append(GateRule(
                rule_id="R6_MARKET_OPEN",
                description="Status pasar sesuai",
                status=GateCheckStatus.PASS,
                detail=f"Market open: {self.market_open}",
            ))

        # R7: Model performance
        if self.model_degraded and SignalSource.MODEL_PREDICTION in config.enabled_sources:
            rules.append(GateRule(
                rule_id="R7_MODEL_PERF",
                description="Model tidak boleh degraded untuk sinyal model",
                status=GateCheckStatus.WARNING,
                detail="Model degraded — sinyal model_prediction tidak dapat dipercaya. "
                       "Nonaktifkan MODEL_PREDICTION atau retrain model.",
                is_blocking=False,
            ))
        else:
            rules.append(GateRule(
                rule_id="R7_MODEL_PERF",
                description="Performa model sesuai",
                status=GateCheckStatus.PASS,
            ))

        # R8: Market scope — IDX vs global
        if (
            MarketScope.GLOBAL in config.market_scope
            or MarketScope.MULTI_ASSET in config.market_scope
        ):
            if self.env == "live":
                rules.append(GateRule(
                    rule_id="R8_GLOBAL_SCOPE",
                    description=(
                        "Instrumen global/multi-asset di live "
                        "memerlukan konfirmasi tambahan"
                    ),
                    status=GateCheckStatus.WARNING,
                    detail=(
                        "Pastikan broker mendukung instrumen global dan "
                        "aturan risk untuk multi-asset telah diset."
                    ),
                    is_blocking=False,
                ))
            else:
                rules.append(GateRule(
                    rule_id="R8_GLOBAL_SCOPE",
                    description="Cakupan global/multi-asset diizinkan di non-live",
                    status=GateCheckStatus.PASS,
                ))
        else:
            rules.append(GateRule(
                rule_id="R8_GLOBAL_SCOPE",
                description="Cakupan pasar: IDX only",
                status=GateCheckStatus.PASS,
            ))

        # R9: Min confidence
        if config.min_confidence < 50:
            rules.append(GateRule(
                rule_id="R9_CONFIDENCE",
                description="Min confidence >= 50 untuk auto-eksekusi",
                status=GateCheckStatus.WARNING,
                detail=f"Min confidence {config.min_confidence} terlalu rendah. "
                       "Disarankan minimal 65.",
                is_blocking=False,
            ))
        else:
            rules.append(GateRule(
                rule_id="R9_CONFIDENCE",
                description=f"Min confidence {config.min_confidence} (>= 50)",
                status=GateCheckStatus.PASS,
            ))

        # R10: Auto-sell
        if config.auto_sell and not config.confirmed_risk_understood:
            rules.append(GateRule(
                rule_id="R10_AUTO_SELL",
                description="Auto-sell memerlukan konfirmasi pemahaman risiko",
                status=GateCheckStatus.FAIL,
                detail="Centang 'Saya memahami risiko kehilangan modal' "
                    "untuk mengaktifkan auto-sell.",
            ))
        else:
            rules.append(GateRule(
                rule_id="R10_AUTO_SELL",
                description="Auto-sell sesuai aturan",
                status=GateCheckStatus.PASS,
            ))

        # R11: Leverage config
        lev = config.leverage_config
        if lev.enabled:
            if not lev.confirmed_risk:
                rules.append(GateRule(
                    rule_id="R11_LEVERAGE",
                    description="Leverage aktif — konfirmasi risiko wajib",
                    status=GateCheckStatus.FAIL,
                    detail="Centang 'Saya memahami risiko leverage' untuk mengaktifkan leverage.",
                ))
            elif not lev.confirmed_margin_call:
                rules.append(GateRule(
                    rule_id="R11_LEVERAGE",
                    description="Leverage aktif — konfirmasi margin call wajib",
                    status=GateCheckStatus.FAIL,
                    detail="Centang 'Saya memahami risiko margin call' "
                    "untuk mengaktifkan leverage.",
                ))
            elif not lev.confirmed_liquidation:
                rules.append(GateRule(
                    rule_id="R11_LEVERAGE",
                    description="Leverage aktif — konfirmasi likuidasi paksa wajib",
                    status=GateCheckStatus.FAIL,
                    detail="Centang 'Saya memahami risiko likuidasi paksa' "
                    "untuk mengaktifkan leverage.",
                ))
            elif lev.max_leverage > 10.0:
                rules.append(GateRule(
                    rule_id="R11_LEVERAGE",
                    description=f"Max leverage {lev.max_leverage}x "
                    "sangat tinggi",
                    status=GateCheckStatus.WARNING,
                    detail="Leverage >10x berisiko sangat besar. Pastikan hanya untuk "
                           "instrumen forex/derivatif dengan volatilitas terkendali.",
                    is_blocking=False,
                ))
            else:
                rules.append(GateRule(
                    rule_id="R11_LEVERAGE",
                    description=f"Leverage aktif (max {lev.max_leverage}x) "
                    "— semua konfirmasi lengkap",
                    status=GateCheckStatus.PASS,
                ))
        else:
            rules.append(GateRule(
                rule_id="R11_LEVERAGE",
                description="Leverage tidak diaktifkan",
                status=GateCheckStatus.PASS,
            ))

        # Aggregate
        blocking = sum(1 for r in rules if r.status == GateCheckStatus.FAIL and r.is_blocking)
        warnings = sum(1 for r in rules if r.status == GateCheckStatus.WARNING)
        passed = blocking == 0

        summary = (
            f"Gate: {'PASS' if passed else 'FAIL'} — "
            f"{len(rules)} aturan, {blocking} blocking, {warnings} warning. "
        )
        if passed and warnings > 0:
            summary += f"{warnings} peringatan non-blocking perlu diperhatikan."
        elif passed:
            summary += "Semua aturan lulus."
        else:
            failed_rules = [
                r.rule_id for r in rules
                if r.status == GateCheckStatus.FAIL and r.is_blocking
            ]
            summary += f"Aturan gagal: {', '.join(failed_rules)}"

        return GateResult(
            passed=passed,
            rules=rules,
            blocking_count=blocking,
            warning_count=warnings,
            summary=summary,
        )

    def check_can_enable(
        self,
        config: AutomationConfig,
        source: SignalSource,
    ) -> tuple[bool, str]:
        """Periksa apakah satu sumber sinyal spesifik boleh dicentang.

        Args:
            config: Konfigurasi user.
            source: Sumber sinyal yang ingin diaktifkan.

        Returns:
            Tuple (can_enable, reason).
        """
        if self.env == "research" and config.execution_mode == ExecutionMode.FULL_AUTO:
            return False, "FULL_AUTO tidak diizinkan di environment research."

        if source == SignalSource.MODEL_PREDICTION and self.model_degraded:
            return False, "Model degraded — tidak boleh mengaktifkan sinyal model."

        if not self.market_open and config.execution_mode == ExecutionMode.FULL_AUTO:
            return False, "Pasar tutup — FULL_AUTO tidak dapat diaktifkan."

        if self.circuit_breaker_triggered:
            return False, "Circuit breaker aktif — semua otomatisasi diblokir."

        if self.daily_loss_halted:
            return False, "Daily loss limit tercapai — otomatisasi diblokir untuk hari ini."

        if self.env == "live" and not self.live_approved:
            return False, "Live approval token belum disetujui."

        if config.execution_mode != ExecutionMode.MANUAL:
            if not config.confirmed_paper_30d:
                return False, "Centang 'Paper trading 30 hari' terlebih dahulu."
            if not config.confirmed_risk_understood:
                return False, "Centang 'Pemahaman risiko' terlebih dahulu."
            if not config.confirmed_risk_limits:
                return False, "Centang 'Risk limits disetujui' terlebih dahulu."

        return True, "OK"


# ---------------------------------------------------------------------------
# Execution Plan
# ---------------------------------------------------------------------------


@dataclass
class PlanOrder:
    """Satu order dalam rencana eksekusi."""

    ticker: str
    side: str  # buy, sell
    shares: int
    price: float
    source: SignalSource
    confidence: float
    readiness_level: str
    risk_score: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    rejection_reason: str | None = None


@dataclass
class ExecutionPlan:
    """Rencana eksekusi dari hasil screening/sinyal ke order."""

    plan_id: str
    created_at: str
    status: PlanStatus
    orders: list[PlanOrder] = field(default_factory=list)
    total_value: float = 0.0
    total_risk: float = 0.0
    passed_count: int = 0
    rejected_count: int = 0
    rejection_reasons: list[str] = field(default_factory=list)
    gate_result: GateResult | None = None
    summary: str = ""


class PlanBuilder:
    """Membangun rencana eksekusi dari sinyal/screening hasil.

    Pipeline:
    1. Terima daftar sinyal (dari AdvisoryEngine, model, pattern, dll)
    2. Filter berdasarkan config (source, confidence, market scope)
    3. Validasi readiness gate per instrumen
    4. Hitung position sizing via RiskEngine
    5. Validasi IDX rules (lot size, tick size)
    6. Buat ExecutionPlan dengan PlanOrders
    """

    def __init__(
        self,
        min_confidence: float = 65.0,
        max_orders: int = 5,
        max_value: float = 50_000_000,
        lot_size: int = 100,
    ) -> None:
        self.min_confidence = min_confidence
        self.max_orders = max_orders
        self.max_value = max_value
        self.lot_size = lot_size

    @staticmethod
    def _generate_plan_id() -> str:
        """Generate a unique, sortable plan ID (timestamp + uuid4 suffix)."""
        ts = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
        return f"PLAN-{ts}-{uuid4().hex[:6]}"

    def build(
        self,
        signals: list[dict[str, Any]],
        config: AutomationConfig,
        readiness_reports: dict[str, Any] | None = None,
        risk_assessments: dict[str, Any] | None = None,
    ) -> ExecutionPlan:
        """Bangun rencana eksekusi dari daftar sinyal.

        Args:
            signals: Daftar sinyal dengan keys: ticker, side, source,
                     confidence, price, recommendation.
            config: Konfigurasi otomatisasi.
            readiness_reports: Dict ticker → InstrumentReadinessReport.
            risk_assessments: Dict ticker → RiskAssessment.

        Returns:
            ExecutionPlan dengan orders yang lolos filter.
        """
        plan_id = self._generate_plan_id()

        orders: list[PlanOrder] = []
        rejections: list[str] = []
        total_value = 0.0
        total_risk = 0.0

        ready_levels = {"ready", "conditional"}

        for sig in signals:
            ticker = sig.get("ticker", "")
            side = sig.get("side", "buy")
            source_str = sig.get("source", "screening_ai")
            confidence = float(sig.get("confidence", 0.0))
            price = float(sig.get("price", 0.0))
            recommendation = sig.get("recommendation", "")

            # Filter 1: Source enabled
            try:
                source = SignalSource(source_str)
            except ValueError:
                source = SignalSource.SCREENING_AI

            if source not in config.enabled_sources:
                rejections.append(f"{ticker}: source {source.value} tidak diaktifkan")
                continue

            # Filter 2: Confidence
            if confidence < config.min_confidence:
                rejections.append(
                    f"{ticker}: confidence {confidence:.1f} < min {config.min_confidence}"
                )
                continue

            # Filter 3: Readiness gate
            if readiness_reports:
                report = readiness_reports.get(ticker)
                if report and hasattr(report, "readiness_level"):
                    level_str = report.readiness_level.value if hasattr(
                        report.readiness_level, "value",
                    ) else str(report.readiness_level)
                    if level_str not in ready_levels:
                        rejections.append(f"{ticker}: readiness {level_str} — tidak siap")
                        continue
                    readiness_level = level_str
                else:
                    readiness_level = "unknown"
            else:
                readiness_level = "not_checked"

            # Filter 4: Max orders
            if len(orders) >= config.max_orders_per_session:
                rejections.append(
                    f"{ticker}: maksimum {config.max_orders_per_session} order tercapai"
                )
                continue

            # Filter 5: Recommendation filter (only buy/strong_buy for auto)
            if (
                recommendation
                and recommendation not in ("strong_buy", "buy")
                and not config.auto_sell
            ):
                rejections.append(
                    f"{ticker}: recommendation '{recommendation}' "
                    "— auto-sell tidak diaktifkan"
                )
                continue

            # Position sizing
            risk_data = risk_assessments.get(ticker) if risk_assessments else None
            if risk_data and hasattr(risk_data, "position_size"):
                shares = int(risk_data.position_size)
                stop_loss = float(getattr(risk_data, "stop_loss", 0.0))
                take_profit = float(getattr(risk_data, "take_profit", 0.0))
                risk_score = float(getattr(risk_data, "atr", 0.0))
            else:
                # Fallback: simple lot-based sizing
                target_value = min(
                    config.max_value_per_session / max(1, config.max_orders_per_session),
                    10_000_000,
                )
                shares = (
                    int(target_value / price / self.lot_size) * self.lot_size
                    if price > 0 else 0
                )
                stop_loss = price * 0.95
                take_profit = price * 1.10
                risk_score = 0.0

            # Filter 6: Lot size validation
            if shares % self.lot_size != 0 or shares <= 0:
                shares = (shares // self.lot_size) * self.lot_size
                if shares <= 0:
                    rejections.append(f"{ticker}: shares tidak valid setelah lot rounding")
                    continue

            # Filter 7: Max value per session
            order_value = shares * price
            if total_value + order_value > config.max_value_per_session:
                remaining = config.max_value_per_session - total_value
                if remaining > 0:
                    shares = int(remaining / price / self.lot_size) * self.lot_size
                    order_value = shares * price
                    if shares <= 0:
                        rejections.append(f"{ticker}: tidak ada sisa value untuk sesi")
                        continue
                else:
                    rejections.append(f"{ticker}: max value per sesi tercapai")
                    continue

            orders.append(PlanOrder(
                ticker=ticker,
                side=side,
                shares=shares,
                price=price,
                source=source,
                confidence=confidence,
                readiness_level=readiness_level,
                risk_score=risk_score,
                stop_loss=stop_loss,
                take_profit=take_profit,
            ))
            total_value += order_value
            total_risk += abs(price - stop_loss) * shares

        plan = ExecutionPlan(
            plan_id=plan_id,
            created_at=datetime.now(UTC).isoformat(),
            status=PlanStatus.VALIDATED if orders else PlanStatus.REJECTED,
            orders=orders,
            total_value=round(total_value, 2),
            total_risk=round(total_risk, 2),
            passed_count=len(orders),
            rejected_count=len(rejections),
            rejection_reasons=rejections,
            summary=(
                f"Plan {plan_id}: {len(orders)} order lolos, "
                f"{len(rejections)} ditolak. "
                f"Total value: Rp {total_value:,.0f}. "
                f"Total risk: Rp {total_risk:,.0f}."
            ),
        )
        return plan


# ---------------------------------------------------------------------------
# Auto Executor
# ---------------------------------------------------------------------------


@dataclass
class ExecutionResult:
    """Hasil eksekusi satu order."""

    ticker: str
    side: str
    shares: int
    price: float
    status: str  # filled, rejected, pending
    fill_price: float = 0.0
    commission: float = 0.0
    sales_tax: float = 0.0
    rejection_reason: str | None = None
    order_id: str | None = None


@dataclass
class ExecutionBatchResult:
    """Hasil eksekusi batch dari semua order dalam plan."""

    plan_id: str
    executed_at: str
    results: list[ExecutionResult] = field(default_factory=list)
    filled_count: int = 0
    rejected_count: int = 0
    total_commission: float = 0.0
    total_sales_tax: float = 0.0
    total_value: float = 0.0
    summary: str = ""


class AutoExecutor:
    """Eksekutor otomatis yang menjalankan ExecutionPlan via broker.

    Menggunakan BrokerAdapter (Mock/Paper/Real) untuk submit order.
    Holds a persistent OMS instance to preserve order history across calls.
    """

    def __init__(self, broker: Any | None = None, oms: Any | None = None) -> None:
        from quant.execution.brokers import MockBroker
        from quant.execution.oms import OMS

        self.broker = broker or MockBroker()
        self.oms = oms or OMS()

    def execute_plan(self, plan: ExecutionPlan) -> ExecutionBatchResult:
        """Eksekusi semua order dalam plan.

        Args:
            plan: Rencana eksekusi yang sudah divalidasi.

        Returns:
            ExecutionBatchResult dengan hasil per order.
        """
        from quant.execution.oms import OrderSide, OrderStatus, OrderType

        results: list[ExecutionResult] = []
        filled = 0
        rejected = 0
        total_comm = 0.0
        total_tax = 0.0
        total_val = 0.0

        for plan_order in plan.orders:
            side = OrderSide.BUY if plan_order.side == "buy" else OrderSide.SELL

            order = self.oms.create_order(
                ticker=plan_order.ticker,
                side=side,
                shares=plan_order.shares,
                order_type=OrderType.LIMIT,
                price=plan_order.price,
            )

            self.oms.transition(order.id, OrderStatus.PENDING)

            fill = self.broker.submit(order)

            if fill is not None:
                self.oms.add_fill(order.id, fill.shares, fill.price)
                results.append(ExecutionResult(
                    ticker=plan_order.ticker,
                    side=plan_order.side,
                    shares=fill.shares,
                    price=plan_order.price,
                    status="filled",
                    fill_price=fill.price,
                    commission=fill.commission,
                    sales_tax=fill.sales_tax,
                    order_id=order.id,
                ))
                filled += 1
                total_comm += fill.commission
                total_tax += fill.sales_tax
                total_val += fill.shares * fill.price
            else:
                results.append(ExecutionResult(
                    ticker=plan_order.ticker,
                    side=plan_order.side,
                    shares=plan_order.shares,
                    price=plan_order.price,
                    status="rejected",
                    rejection_reason="Broker rejected order",
                    order_id=order.id,
                ))
                rejected += 1

        plan.status = PlanStatus.COMPLETED if rejected == 0 else PlanStatus.PARTIAL

        summary = (
            f"Executed {plan.plan_id}: {filled} filled, {rejected} rejected. "
            f"Value: Rp {total_val:,.0f}. Commission: Rp {total_comm:,.0f}."
        )

        return ExecutionBatchResult(
            plan_id=plan.plan_id,
            executed_at=datetime.now(UTC).isoformat(),
            results=results,
            filled_count=filled,
            rejected_count=rejected,
            total_commission=round(total_comm, 2),
            total_sales_tax=round(total_tax, 2),
            total_value=round(total_val, 2),
            summary=summary,
        )

    def execute_rebalance(
        self,
        rebalance_orders: list[dict[str, object]],
        prices: dict[str, float] | None = None,
    ) -> ExecutionBatchResult:
        """Eksekusi rebalance orders dari PortfolioManager.compute_rebalance_orders().

        Mengkonversi rebalance orders (list of dict dengan ticker, side, shares,
        value) menjadi ExecutionPlan dan mengeksekusinya via broker.

        Args:
            rebalance_orders: List of order dicts from compute_rebalance_orders().
            prices: Optional dict mapping ticker to current price (for limit orders).
                If not provided, uses market orders.

        Returns:
            ExecutionBatchResult dengan hasil eksekusi.
        """
        from quant.execution.oms import OrderSide, OrderStatus, OrderType

        results: list[ExecutionResult] = []
        filled = 0
        rejected = 0
        total_comm = 0.0
        total_tax = 0.0
        total_val = 0.0

        for order_dict in rebalance_orders:
            ticker = str(order_dict.get("ticker", ""))
            side_str = str(order_dict.get("side", "buy"))
            shares = int(order_dict.get("shares", 0))
            if shares <= 0 or not ticker:
                continue

            side = OrderSide.BUY if side_str == "buy" else OrderSide.SELL
            price = prices.get(ticker) if prices else None

            order_type = OrderType.LIMIT if price else OrderType.MARKET

            order = self.oms.create_order(
                ticker=ticker,
                side=side,
                shares=shares,
                order_type=order_type,
                price=price,
            )

            self.oms.transition(order.id, OrderStatus.PENDING)

            fill = self.broker.submit(order)

            if fill is not None:
                self.oms.add_fill(order.id, fill.shares, fill.price)
                results.append(ExecutionResult(
                    ticker=ticker,
                    side=side_str,
                    shares=fill.shares,
                    price=fill.price,
                    status="filled",
                    fill_price=fill.price,
                    commission=fill.commission,
                    sales_tax=fill.sales_tax,
                    order_id=order.id,
                ))
                filled += 1
                total_comm += fill.commission
                total_tax += fill.sales_tax
                total_val += fill.shares * fill.price
            else:
                results.append(ExecutionResult(
                    ticker=ticker,
                    side=side_str,
                    shares=shares,
                    price=price or 0.0,
                    status="rejected",
                    rejection_reason="Broker rejected rebalance order",
                    order_id=order.id,
                ))
                rejected += 1

        summary = (
            f"Rebalance executed: {filled} filled, {rejected} rejected. "
            f"Value: Rp {total_val:,.0f}. Commission: Rp {total_comm:,.0f}."
        )

        return ExecutionBatchResult(
            plan_id=f"REBALANCE-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}",
            executed_at=datetime.now(UTC).isoformat(),
            results=results,
            filled_count=filled,
            rejected_count=rejected,
            total_commission=round(total_comm, 2),
            total_sales_tax=round(total_tax, 2),
            total_value=round(total_val, 2),
            summary=summary,
        )


# ---------------------------------------------------------------------------
# Automation Orchestrator
# ---------------------------------------------------------------------------


class AutomationOrchestrator:
    """Menyatukan gate → plan → execute untuk otomatisasi trading.

    Flow:
    1. User mengatur config (centang pilihan) di FE
    2. AutomationGate memeriksa config — jika pass, lanjut
    3. PlanBuilder membuat ExecutionPlan dari sinyal
    4. AutoExecutor menjalankan plan via broker
    5. Hasil dilaporkan ke user
    """

    def __init__(
        self,
        gate: AutomationGate | None = None,
        plan_builder: PlanBuilder | None = None,
        executor: AutoExecutor | None = None,
    ) -> None:
        self.gate = gate or AutomationGate()
        self.plan_builder = plan_builder or PlanBuilder()
        self.executor = executor or AutoExecutor()
        self._config: AutomationConfig | None = None
        self._last_gate_result: GateResult | None = None
        self._last_plan: ExecutionPlan | None = None
        self._last_execution: ExecutionBatchResult | None = None

    @property
    def config(self) -> AutomationConfig | None:
        return self._config

    @property
    def last_gate_result(self) -> GateResult | None:
        return self._last_gate_result

    @property
    def last_plan(self) -> ExecutionPlan | None:
        return self._last_plan

    @property
    def last_execution(self) -> ExecutionBatchResult | None:
        return self._last_execution

    def configure(self, config: AutomationConfig) -> GateResult:
        """Atur konfigurasi dan periksa gate.

        Args:
            config: Konfigurasi otomatisasi dari user.

        Returns:
            GateResult — jika fail, config tidak disimpan.
        """
        result = self.gate.check_config(config)
        self._last_gate_result = result

        if result.can_proceed or config.execution_mode == ExecutionMode.MANUAL:
            self._config = config
        else:
            self._config = None

        return result

    def prepare_plan(
        self,
        signals: list[dict[str, Any]],
        readiness_reports: dict[str, Any] | None = None,
        risk_assessments: dict[str, Any] | None = None,
    ) -> ExecutionPlan:
        """Siapkan rencana eksekusi dari sinyal.

        Tidak mengeksekusi — hanya membuat plan untuk preview user.

        Args:
            signals: Daftar sinyal dari screening/model/advisory.
            readiness_reports: Readiness gate reports per ticker.
            risk_assessments: Risk assessments per ticker.

        Returns:
            ExecutionPlan untuk preview.
        """
        if self._config is None:
            return ExecutionPlan(
                plan_id="PLAN-REJECTED",
                created_at=datetime.now(UTC).isoformat(),
                status=PlanStatus.REJECTED,
                rejection_reasons=["Config belum diset atau gate gagal."],
                summary="Plan rejected: config not set.",
            )

        plan = self.plan_builder.build(
            signals,
            self._config,
            readiness_reports=readiness_reports,
            risk_assessments=risk_assessments,
        )
        plan.gate_result = self._last_gate_result
        self._last_plan = plan
        return plan

    def execute(
        self,
        signals: list[dict[str, Any]],
        readiness_reports: dict[str, Any] | None = None,
        risk_assessments: dict[str, Any] | None = None,
    ) -> ExecutionBatchResult:
        """Siapkan plan dan eksekusi otomatis.

        Menjalankan full pipeline: gate → plan → execute.
        Hanya mengeksekusi jika gate pass dan mode != MANUAL.

        Args:
            signals: Daftar sinyal.
            readiness_reports: Readiness reports per ticker.
            risk_assessments: Risk assessments per ticker.

        Returns:
            ExecutionBatchResult dengan hasil eksekusi.
        """
        if self._config is None:
            return ExecutionBatchResult(
                plan_id="N/A",
                executed_at=datetime.now(UTC).isoformat(),
                summary="Config belum diset atau gate gagal.",
            )

        if self._config.execution_mode == ExecutionMode.MANUAL:
            plan = self.prepare_plan(signals, readiness_reports, risk_assessments)
            return ExecutionBatchResult(
                plan_id=plan.plan_id,
                executed_at=datetime.now(UTC).isoformat(),
                summary=f"Mode manual — plan dibuat tapi tidak dieksekusi. {plan.summary}",
            )

        # Re-check gate
        gate_result = self.gate.check_config(self._config)
        self._last_gate_result = gate_result

        if not gate_result.can_proceed:
            return ExecutionBatchResult(
                plan_id="N/A",
                executed_at=datetime.now(UTC).isoformat(),
                summary=f"Gate gagal: {gate_result.summary}",
            )

        # Build plan
        plan = self.prepare_plan(signals, readiness_reports, risk_assessments)

        if plan.status == PlanStatus.REJECTED or not plan.orders:
            return ExecutionBatchResult(
                plan_id=plan.plan_id,
                executed_at=datetime.now(UTC).isoformat(),
                summary=f"Tidak ada order yang lolos filter. {plan.summary}",
            )

        # Execute
        result = self.executor.execute_plan(plan)
        self._last_execution = result
        return result

    def rebalance(
        self,
        portfolio_manager: Any,
        prices: dict[str, float],
        drift_threshold_pct: float = 5.0,
    ) -> ExecutionBatchResult:
        """Rebalance portfolio ke target weights via AutoExecutor (Gap #12).

        Flow:
        1. Cek apakah drift melebihi threshold
        2. Compute rebalance orders via PortfolioManager
        3. Eksekusi orders via AutoExecutor.execute_rebalance()

        Args:
            portfolio_manager: PortfolioManager instance dengan target_weights.
            prices: Dict mapping ticker to current price.
            drift_threshold_pct: Rebalance hanya jika drift > threshold.

        Returns:
            ExecutionBatchResult dengan hasil eksekusi rebalance.
        """
        # 1. Cek drift
        needs_rebalance = portfolio_manager.needs_rebalance(
            prices, threshold_pct=drift_threshold_pct,
        )

        if not needs_rebalance:
            return ExecutionBatchResult(
                plan_id="REBALANCE-SKIP",
                executed_at=datetime.now(UTC).isoformat(),
                summary=f"Drift < {drift_threshold_pct}% — no rebalance needed.",
            )

        # 2. Compute rebalance orders
        orders = portfolio_manager.compute_rebalance_orders(prices)

        if not orders:
            return ExecutionBatchResult(
                plan_id="REBALANCE-EMPTY",
                executed_at=datetime.now(UTC).isoformat(),
                summary="Rebalance needed but no orders generated (rounding to lot size).",
            )

        # 3. Cek gate jika config diset
        if self._config is not None:
            gate_result = self.gate.check_config(self._config)
            self._last_gate_result = gate_result
            if not gate_result.can_proceed:
                return ExecutionBatchResult(
                    plan_id="REBALANCE-GATE-FAIL",
                    executed_at=datetime.now(UTC).isoformat(),
                    summary=f"Gate gagal untuk rebalance: {gate_result.summary}",
                )

        # 4. Eksekusi
        result = self.executor.execute_rebalance(orders, prices)
        self._last_execution = result
        return result
