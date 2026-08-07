"""回测框架契约层。禁止依赖 engine / analytics / reporting。"""

from .config import (
    ClockConfig,
    ConstraintConfig,
    CostConfig,
    CostRate,
    ExecutionConfig,
    LongOnlyFactorBacktestConfig,
    LongOnlyFactorBacktestRequest,
    LongOnlyFactorReportRequest,
    LongOnlyFactorReportResult,
    PortfolioReportConfig,
    RegressionConfig,
    SelectionConfig,
    WeightingConfig,
    asdict_deep,
)
from .frames import (
    FactorFrame,
    MarketPriceFrame,
    PortfolioInitialState,
    PortfolioLiquidityData,
    ResolvedLongOnlyBacktestData,
    TradabilityFrame,
)
from .records import (
    DatasetRef,
    FillRecord,
    OrderRecord,
    RunArtifact,
    RunManifest,
    fills_to_frame,
    orders_to_frame,
)
from .reports import (
    AlphaBetaReport,
    IndexSelectionReport,
    LongOnlyFactorBacktestResult,
    PerformanceStats,
    PortfolioBacktestDiagnostics,
    PortfolioConstraintReport,
    PortfolioPerformanceReport,
    StyleExposureReport,
)

__all__ = [
    "ClockConfig", "ConstraintConfig", "CostConfig", "CostRate", "ExecutionConfig",
    "LongOnlyFactorBacktestConfig", "LongOnlyFactorBacktestRequest",
    "LongOnlyFactorReportRequest", "LongOnlyFactorReportResult",
    "PortfolioReportConfig", "RegressionConfig", "SelectionConfig", "WeightingConfig", "asdict_deep",
    "FactorFrame", "MarketPriceFrame", "PortfolioInitialState", "PortfolioLiquidityData",
    "ResolvedLongOnlyBacktestData", "TradabilityFrame",
    "DatasetRef", "FillRecord", "OrderRecord", "RunArtifact", "RunManifest",
    "fills_to_frame", "orders_to_frame",
    "AlphaBetaReport", "IndexSelectionReport", "LongOnlyFactorBacktestResult", "PerformanceStats",
    "PortfolioBacktestDiagnostics", "PortfolioConstraintReport", "PortfolioPerformanceReport",
    "StyleExposureReport",
]
