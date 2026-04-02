"""
Statistical Analyzer for A/B testing significance testing and composite scoring.

Provides Welch's t-test for statistical significance, Cohen's d effect size,
and composite score calculation for multi-dimensional metrics.

Part of the A/B testing infrastructure for determining if improvements
are statistically significant.
"""
import logging
from dataclasses import dataclass
from typing import Tuple

import numpy as np
from scipy import stats

log = logging.getLogger(__name__)


@dataclass
class SignificanceResult:
    """
    Result of statistical significance testing.

    Contains all statistical metrics needed to determine if an improvement
    is significant: p-value, effect size, confidence intervals, and the
    final determination based on thresholds.

    Attributes:
        p_value: P-value from Welch's t-test (one-sided, improvement > baseline).
        effect_size: Cohen's d effect size (standardized mean difference).
        relative_improvement: Relative improvement as (improvement - baseline) / baseline.
        is_significant: True if BOTH p_value < threshold AND relative_improvement > threshold.
        baseline_mean: Mean of baseline variant scores.
        improvement_mean: Mean of improvement variant scores.
        confidence_interval: 95% confidence interval for the mean difference (low, high).
        t_statistic: T-statistic from the test.
        degrees_of_freedom: Welch-Satterthwaite degrees of freedom.
        sample_size_baseline: Number of baseline samples.
        sample_size_improvement: Number of improvement samples.
    """

    p_value: float
    effect_size: float
    relative_improvement: float
    is_significant: bool
    baseline_mean: float
    improvement_mean: float
    confidence_interval: Tuple[float, float]
    t_statistic: float
    degrees_of_freedom: float
    sample_size_baseline: int
    sample_size_improvement: int


class StatisticalAnalyzer:
    """
    Statistical analysis for A/B testing.

    Provides two core functions:
    1. Statistical significance testing using Welch's t-test
    2. Composite score calculation for multi-dimensional metrics

    This is pure computation - no I/O or database access. Designed for
    research software with clear statistical methodology.

    Example:
        analyzer = StatisticalAnalyzer()

        # Significance testing
        result = analyzer.compute_significance(
            baseline_scores=[0.5, 0.6, 0.55, 0.58, 0.52],
            improvement_scores=[0.7, 0.75, 0.72, 0.68, 0.73],
        )
        print(f"Significant: {result.is_significant}, p={result.p_value:.4f}")

        # Composite scoring
        score = analyzer.compute_composite_score(
            quality=0.8,
            latency_ms=500.0,
            is_error=False,
            weights={"quality": 0.5, "latency": 0.3, "error_rate": 0.2},
        )
        print(f"Composite score: {score:.3f}")
    """

    def compute_significance(
        self,
        baseline_scores: list[float],
        improvement_scores: list[float],
        p_threshold: float = 0.05,
        effect_threshold: float = 0.10,
    ) -> SignificanceResult:
        """
        Compute statistical significance using Welch's t-test.

        Uses one-sided Welch's t-test (unequal variance assumed) to determine
        if improvement variant is significantly better than baseline.

        Per user decision: Significance requires BOTH:
        - p_value < p_threshold (default 0.05)
        - relative_improvement > effect_threshold (default 0.10 = 10%)

        Methodology:
        1. Welch's t-test with alternative='greater' (improvement > baseline)
        2. Cohen's d effect size with pooled standard deviation
        3. Relative improvement = (improvement_mean - baseline_mean) / baseline_mean
        4. 95% confidence interval for mean difference
        5. Welch-Satterthwaite degrees of freedom

        Edge cases handled:
        - Zero variance: effect_size = 0.0
        - Zero baseline mean: use Cohen's d as fallback for relative improvement
        - Small samples: Welch's t-test is robust for unequal variance

        Args:
            baseline_scores: List of composite scores for baseline variant.
            improvement_scores: List of composite scores for improvement variant.
            p_threshold: Significance level (default 0.05).
            effect_threshold: Minimum relative improvement required (default 0.10 = 10%).

        Returns:
            SignificanceResult with all statistical metrics and determination.
        """
        log.info(
            f"Computing significance: baseline n={len(baseline_scores)}, "
            f"improvement n={len(improvement_scores)}"
        )

        baseline = np.array(baseline_scores)
        improvement = np.array(improvement_scores)

        n1, n2 = len(baseline), len(improvement)
        mean1, mean2 = np.mean(baseline), np.mean(improvement)
        var1, var2 = np.var(baseline, ddof=1), np.var(improvement, ddof=1)
        std1, std2 = np.std(baseline, ddof=1), np.std(improvement, ddof=1)

        # Welch's t-test (unequal variance)
        # alternative='greater' means we test: improvement > baseline
        test_result = stats.ttest_ind(
            improvement,
            baseline,
            equal_var=False,  # Welch's t-test
            alternative="greater",  # One-sided test
        )

        # Welch-Satterthwaite degrees of freedom
        if var1 == 0 and var2 == 0:
            # Both groups have zero variance (identical values)
            df = n1 + n2 - 2
        else:
            # Standard Welch-Satterthwaite formula
            numerator = (var1 / n1 + var2 / n2) ** 2
            denominator = (var1 / n1) ** 2 / (n1 - 1) + (var2 / n2) ** 2 / (n2 - 1)
            df = numerator / denominator if denominator > 0 else n1 + n2 - 2

        # Cohen's d with pooled standard deviation
        pooled_std = np.sqrt(((n1 - 1) * std1**2 + (n2 - 1) * std2**2) / (n1 + n2 - 2))
        if pooled_std > 0:
            cohens_d = (mean2 - mean1) / pooled_std
        else:
            # Zero variance - all values identical
            cohens_d = 0.0

        # Relative improvement: (improvement - baseline) / baseline
        if mean1 > 0:
            relative = (mean2 - mean1) / mean1
        else:
            # Baseline mean is zero - fall back to Cohen's d
            log.warning(
                "Baseline mean is zero, using Cohen's d as fallback for relative improvement"
            )
            relative = cohens_d

        # 95% confidence interval for mean difference
        se = np.sqrt(var1 / n1 + var2 / n2)
        if se > 0:
            # Two-sided 95% CI
            t_crit = stats.t.ppf(0.975, df)  # 97.5th percentile for two-sided 95% CI
            diff = mean2 - mean1
            ci_low = diff - t_crit * se
            ci_high = diff + t_crit * se
        else:
            # Zero standard error - no variance
            diff = mean2 - mean1
            ci_low = ci_high = diff

        # Significance: BOTH conditions must be met
        is_significant = (
            test_result.pvalue < p_threshold and relative > effect_threshold
        )

        result = SignificanceResult(
            p_value=test_result.pvalue,
            effect_size=cohens_d,
            relative_improvement=relative,
            is_significant=is_significant,
            baseline_mean=mean1,
            improvement_mean=mean2,
            confidence_interval=(ci_low, ci_high),
            t_statistic=test_result.statistic,
            degrees_of_freedom=df,
            sample_size_baseline=n1,
            sample_size_improvement=n2,
        )

        log.info(
            f"Significance result: p={result.p_value:.4f}, "
            f"relative_improvement={result.relative_improvement:.2%}, "
            f"is_significant={result.is_significant}"
        )

        return result

    def compute_composite_score(
        self,
        quality: float,
        latency_ms: float,
        is_error: bool,
        weights: dict[str, float],
        latency_baseline: float = 1000.0,
    ) -> float:
        """
        Compute weighted composite score from multiple metrics.

        Normalizes all metrics to [0, 1] where higher is better, then applies
        weights to produce a single composite score.

        Normalization:
        - Quality: Already 0-1, higher is better (no transformation)
        - Latency: Inverse normalized: score = 1 - (latency / (2 * baseline)), clamped [0, 1]
        - Error: Binary: 0.0 if error, 1.0 if success

        Composite = quality * w_quality + latency_score * w_latency + error_score * w_error

        Args:
            quality: Quality score from QualityJudgeService (0.0-1.0).
            latency_ms: Execution latency in milliseconds.
            is_error: True if execution errored, False if successful.
            weights: Dict with keys 'quality', 'latency', 'error_rate' and values summing to 1.0.
            latency_baseline: Baseline latency for normalization (default 1000ms).

        Returns:
            Composite score in [0, 1], higher is better.
        """
        # Normalize latency: lower latency = higher score
        latency_score = self._normalize_latency(latency_ms, latency_baseline)

        # Error score: binary
        error_score = 0.0 if is_error else 1.0

        # Weighted sum
        w_quality = weights.get("quality", 0.5)
        w_latency = weights.get("latency", 0.3)
        w_error = weights.get("error_rate", 0.2)

        composite = (
            quality * w_quality + latency_score * w_latency + error_score * w_error
        )

        # Clamp to [0, 1] just in case
        composite = max(0.0, min(1.0, composite))

        log.debug(
            f"Composite score: quality={quality:.3f}, latency={latency_ms:.1f}ms -> {latency_score:.3f}, "
            f"error={is_error} -> {error_score:.3f}, composite={composite:.3f}"
        )

        return composite

    def _normalize_latency(self, latency_ms: float, baseline: float) -> float:
        """
        Normalize latency to 0-1 score where higher is better.

        Uses inverse normalization: score = 1 - (latency / (2 * baseline))
        Assumes latencies near 2x baseline should score ~0, and 0ms scores 1.0.

        Args:
            latency_ms: Raw latency in milliseconds.
            baseline: Baseline latency for normalization.

        Returns:
            Normalized score in [0, 1], clamped.
        """
        if baseline <= 0:
            baseline = 1000.0  # Fallback to 1 second

        # Lower latency = higher score
        score = 1.0 - (latency_ms / (2 * baseline))

        # Clamp to [0, 1]
        return max(0.0, min(1.0, score))
