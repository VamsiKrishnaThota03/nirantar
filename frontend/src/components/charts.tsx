/** Hand-rolled SVG charts.
 *
 * Shared rules, applied in every form here: thin marks, 4px rounded data-ends
 * anchored to the baseline, hairline solid gridlines one shade off the
 * surface, a 2px surface gap between adjacent fills, selective direct labels
 * rather than a number on every mark, and a hover layer whose hit target is
 * larger than the mark itself.
 */

import { nice, n, n1, pct, seqColor, inkOn, SEQ_STEPS } from "../lib/format";
import { useTooltip } from "./primitives";

const GAP = 2; // surface gap between fills

/* ------------------------------------------------------------------------ */
/* Funnel: ordered stages, so an ordinal single-hue ramp (not categorical).  */
/* ------------------------------------------------------------------------ */

export function Funnel({
  stages,
}: {
  stages: {
    stage: string;
    count: number;
    note: string;
    drop_is_loss?: boolean;
    drop_label?: string;
  }[];
}) {
  const { ref, show, hide, node } = useTooltip();
  const max = Math.max(...stages.map((stage) => stage.count), 1);
  const rowHeight = 56;
  const height = stages.length * rowHeight + 6;
  const labelWidth = 200;

  return (
    <div className="chart-wrap" ref={ref}>
      <svg
        className="chart"
        viewBox={`0 0 760 ${height}`}
        role="img"
        aria-label="Screening cascade: people found, then lost, at each stage"
      >
        {stages.map((stage, index) => {
          const y = index * rowHeight + 4;
          const barMax = 760 - labelWidth - 86;
          const width = Math.max(3, (stage.count / max) * barMax);
          const previous = index === 0 ? null : stages[index - 1].count;
          const dropped = previous === null ? 0 : previous - stage.count;
          // Ordinal ramp: darker as the cascade narrows.
          const fill = SEQ_STEPS[Math.min(SEQ_STEPS.length - 1, 2 + index * 2)];
          return (
            <g key={stage.stage}>
              <text x={0} y={y + 20} style={{ fontSize: 12.5 }}>
                {stage.stage}
              </text>
              {/* The loss sits under the stage name, outside the plot, so it
                  can never collide with a bar or its value label. */}
              {dropped > 0 && (
                <text
                  x={0}
                  y={y + 35}
                  style={{ fontSize: 10.5 }}
                  fill={
                    stage.drop_is_loss === false
                      ? "var(--text-muted)"
                      : "var(--critical)"
                  }
                >
                  −{n(dropped)} {stage.drop_label ?? "lost at this step"}
                </text>
              )}
              <rect
                x={labelWidth}
                y={y + 8}
                width={width}
                height={rowHeight - 22 - GAP}
                rx={4}
                fill={fill}
              />
              <text
                x={labelWidth + width + 9}
                y={y + 25}
                style={{ fontSize: 13, fontWeight: 620 }}
                fill="var(--text-primary)"
              >
                {n(stage.count)}
              </text>
              <rect
                className="hit"
                x={0}
                y={y}
                width={760}
                height={rowHeight}
                onMouseMove={(event) =>
                  show(
                    {
                      title: stage.stage,
                      rows: [
                        { k: "People", v: n(stage.count) },
                        {
                          k: "Share of screened",
                          v: pct(stage.count / max, 1),
                        },
                        ...(dropped > 0
                          ? [
                              {
                                k:
                                  stage.drop_is_loss === false
                                    ? "Fell out (healthy)"
                                    : "Lost at this step",
                                v: n(dropped),
                              },
                            ]
                          : []),
                        { k: "", v: stage.note },
                      ],
                    },
                    event,
                  )
                }
                onMouseLeave={hide}
              />
            </g>
          );
        })}
      </svg>
      {node}
    </div>
  );
}

/* ------------------------------------------------------------------------ */
/* Ranked horizontal bars: one series, one colour.                           */
/* ------------------------------------------------------------------------ */

export function RankedBars({
  rows,
  valueLabel,
  highlightFirst,
  sequential,
  height = 300,
  labelWidth = 168,
  formatValue = (value: number) => n(value),
}: {
  rows: { label: string; value: number; extra?: { k: string; v: string }[] }[];
  valueLabel: string;
  /** Emphasis instead of eight hues: highlight the leader, recede the rest. */
  highlightFirst?: boolean;
  /** Colour by magnitude (only where magnitude is the point). */
  sequential?: boolean;
  height?: number;
  /** Widen when the category names are long, rather than truncating them. */
  labelWidth?: number;
  formatValue?: (value: number) => string;
}) {
  const { ref, show, hide, node } = useTooltip();
  const max = nice(Math.max(...rows.map((row) => row.value), 1));
  const plotWidth = 760 - labelWidth - 74;
  const rowHeight = Math.max(20, Math.min(34, (height - 26) / rows.length));
  const chartHeight = rows.length * rowHeight + 26;
  const ticks = [0, max / 2, max];

  return (
    <div className="chart-wrap" ref={ref}>
      <svg
        className="chart"
        viewBox={`0 0 760 ${chartHeight}`}
        role="img"
        aria-label={`${valueLabel} by category, ranked`}
      >
        {ticks.map((tick) => {
          const x = labelWidth + (tick / max) * plotWidth;
          return (
            <g key={tick}>
              <line
                className="gridline"
                x1={x}
                y1={0}
                x2={x}
                y2={rows.length * rowHeight}
              />
              <text
                className="tick"
                x={x}
                y={rows.length * rowHeight + 15}
                textAnchor="middle"
              >
                {formatValue(tick)}
              </text>
            </g>
          );
        })}
        <line
          className="axisline"
          x1={labelWidth}
          y1={0}
          x2={labelWidth}
          y2={rows.length * rowHeight}
        />
        {rows.map((row, index) => {
          const y = index * rowHeight;
          const width = Math.max(2, (row.value / max) * plotWidth);
          const fill = sequential
            ? seqColor(row.value, max)
            : highlightFirst && index > 0
              ? "var(--seq-250)"
              : "var(--series-1)";
          return (
            <g key={row.label}>
              <text x={0} y={y + rowHeight / 2 + 4} style={{ fontSize: 12 }}>
                {/* Truncation is sized to the label column, so widening the
                    column actually shows more of the name. */}
                {row.label.length > labelWidth / 5.6
                  ? `${row.label.slice(0, Math.floor(labelWidth / 5.6) - 1)}…`
                  : row.label}
              </text>
              <rect
                x={labelWidth}
                y={y + GAP}
                width={width}
                height={rowHeight - GAP * 2}
                rx={4}
                fill={fill}
              />
              <text
                x={labelWidth + width + 8}
                y={y + rowHeight / 2 + 4}
                style={{ fontSize: 11.5, fontWeight: 600 }}
                fill="var(--text-primary)"
              >
                {formatValue(row.value)}
              </text>
              <rect
                className="hit"
                x={0}
                y={y}
                width={760}
                height={rowHeight}
                onMouseMove={(event) =>
                  show(
                    {
                      title: row.label,
                      rows: [
                        { k: valueLabel, v: formatValue(row.value) },
                        ...(row.extra ?? []),
                      ],
                    },
                    event,
                  )
                }
                onMouseLeave={hide}
              />
            </g>
          );
        })}
      </svg>
      {node}
    </div>
  );
}

/* ------------------------------------------------------------------------ */
/* Ordinal bars (aging buckets): ordered categories, single-hue ramp.        */
/* ------------------------------------------------------------------------ */

export function OrdinalBars({
  rows,
}: {
  rows: { bucket: string; count: number; healthy_years_at_stake: number }[];
}) {
  const { ref, show, hide, node } = useTooltip();
  const max = nice(Math.max(...rows.map((row) => row.count), 1));
  const width = 760;
  const plotHeight = 180;
  const slot = width / rows.length;
  const barWidth = Math.min(96, slot - 18);

  return (
    <div className="chart-wrap" ref={ref}>
      <svg
        className="chart"
        viewBox={`0 0 ${width} ${plotHeight + 54}`}
        role="img"
        aria-label="Open care obligations by how far past their clinical deadline they are"
      >
        {[0, max / 2, max].map((tick) => {
          const y = plotHeight - (tick / max) * plotHeight;
          return (
            <g key={tick}>
              <line className="gridline" x1={34} y1={y} x2={width} y2={y} />
              <text className="tick" x={28} y={y + 4} textAnchor="end">
                {n(tick)}
              </text>
            </g>
          );
        })}
        {rows.map((row, index) => {
          const barHeight = Math.max(2, (row.count / max) * plotHeight);
          const x = index * slot + (slot - barWidth) / 2;
          // Ordered categories: the ramp darkens with lateness.
          const fill = SEQ_STEPS[Math.min(SEQ_STEPS.length - 1, index * 2 + 1)];
          const isFirst = index === 0;
          return (
            <g key={row.bucket}>
              <rect
                x={x}
                y={plotHeight - barHeight}
                width={barWidth}
                height={barHeight}
                rx={4}
                fill={isFirst ? "var(--good)" : fill}
              />
              <text
                x={x + barWidth / 2}
                y={plotHeight - barHeight - 7}
                textAnchor="middle"
                style={{ fontSize: 12, fontWeight: 620 }}
                fill="var(--text-primary)"
              >
                {n(row.count)}
              </text>
              <text
                x={x + barWidth / 2}
                y={plotHeight + 17}
                textAnchor="middle"
                className="tick"
                style={{ fontSize: 10.5 }}
              >
                {row.bucket.replace(" overdue", "")}
              </text>
              {index === 0 && (
                <text
                  x={x + barWidth / 2}
                  y={plotHeight + 32}
                  textAnchor="middle"
                  className="tick"
                  style={{ fontSize: 10 }}
                >
                  (on time)
                </text>
              )}
              <rect
                className="hit"
                x={index * slot}
                y={0}
                width={slot}
                height={plotHeight + 24}
                onMouseMove={(event) =>
                  show(
                    {
                      title: row.bucket,
                      rows: [
                        { k: "Obligations", v: n(row.count) },
                        {
                          k: "Healthy years at stake",
                          v: n1(row.healthy_years_at_stake),
                        },
                      ],
                    },
                    event,
                  )
                }
                onMouseLeave={hide}
              />
            </g>
          );
        })}
        <line
          className="axisline"
          x1={34}
          y1={plotHeight}
          x2={width}
          y2={plotHeight}
        />
      </svg>
      {node}
    </div>
  );
}

/* ------------------------------------------------------------------------ */
/* Diverging bars: barrier contributions, two poles + neutral midpoint.      */
/* ------------------------------------------------------------------------ */

export function DivergingBars({
  rows,
}: {
  rows: {
    barrier: string;
    log_odds: number;
    detail: string;
    direction: string;
  }[];
}) {
  const { ref, show, hide, node } = useTooltip();
  const extent = Math.max(...rows.map((row) => Math.abs(row.log_odds)), 0.5);
  const labelWidth = 230;
  const mid = labelWidth + (760 - labelWidth) / 2;
  const half = (760 - labelWidth) / 2 - 46;
  const rowHeight = 27;
  const height = rows.length * rowHeight + 30;

  return (
    <div className="chart-wrap" ref={ref}>
      <svg
        className="chart"
        viewBox={`0 0 760 ${height}`}
        role="img"
        aria-label="How much each barrier raises or lowers the chance this patient does not attend"
      >
        <line
          className="axisline"
          x1={mid}
          y1={0}
          x2={mid}
          y2={rows.length * rowHeight}
        />
        {rows.map((row, index) => {
          const y = index * rowHeight;
          const magnitude = (Math.abs(row.log_odds) / extent) * half;
          const positive = row.log_odds > 0;
          return (
            <g key={row.barrier}>
              <text x={0} y={y + rowHeight / 2 + 4} style={{ fontSize: 11.5 }}>
                {row.barrier.length > 40
                  ? `${row.barrier.slice(0, 39)}…`
                  : row.barrier}
              </text>
              <rect
                x={positive ? mid + GAP : mid - magnitude - GAP}
                y={y + 5}
                width={Math.max(2, magnitude)}
                height={rowHeight - 12}
                rx={4}
                fill={positive ? "var(--critical)" : "var(--series-1)"}
              />
              <text
                x={positive ? mid + magnitude + 8 : mid - magnitude - 8}
                y={y + rowHeight / 2 + 4}
                textAnchor={positive ? "start" : "end"}
                style={{ fontSize: 11, fontWeight: 600 }}
                fill="var(--text-primary)"
              >
                {row.log_odds > 0 ? "+" : ""}
                {row.log_odds.toFixed(2)}
              </text>
              <rect
                className="hit"
                x={0}
                y={y}
                width={760}
                height={rowHeight}
                onMouseMove={(event) =>
                  show(
                    {
                      title: row.barrier,
                      rows: [
                        { k: "Log-odds", v: row.log_odds.toFixed(3) },
                        { k: "Effect", v: row.direction },
                        { k: "", v: row.detail },
                      ],
                    },
                    event,
                  )
                }
                onMouseLeave={hide}
              />
            </g>
          );
        })}
        <text
          x={mid - 6}
          y={rows.length * rowHeight + 18}
          textAnchor="end"
          className="tick"
        >
          ← makes attending more likely
        </text>
        <text
          x={mid + 6}
          y={rows.length * rowHeight + 18}
          className="tick"
        >
          makes attending less likely →
        </text>
      </svg>
      {node}
    </div>
  );
}

/* ------------------------------------------------------------------------ */
/* Paired comparison: two series (conventional vs Nirantar), one axis each.  */
/* Separate charts per measure -- never two y-scales on one plot.            */
/* ------------------------------------------------------------------------ */

export function CompareBars({
  metrics,
}: {
  metrics: {
    label: string;
    conventional: number;
    nirantar: number;
    format: (value: number) => string;
    betterIsLower?: boolean;
  }[];
}) {
  return (
    <div style={{ display: "grid", gap: 18 }}>
      {metrics.map((metric) => {
        const max = Math.max(metric.conventional, metric.nirantar, 1);
        const conventionalWidth = (metric.conventional / max) * 100;
        const nirantarWidth = (metric.nirantar / max) * 100;
        const better = metric.betterIsLower !== false;
        const delta = metric.conventional - metric.nirantar;
        return (
          <div key={metric.label}>
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                fontSize: 12.5,
                color: "var(--text-secondary)",
                marginBottom: 7,
              }}
            >
              <span>{metric.label}</span>
              {delta !== 0 && (
                <span
                  style={{
                    color: better
                      ? "var(--success-text)"
                      : "var(--text-secondary)",
                    fontWeight: 600,
                  }}
                >
                  {better ? "−" : "+"}
                  {metric.format(Math.abs(delta))}
                </span>
              )}
            </div>
            <div style={{ display: "grid", gap: GAP + 2 }}>
              <Bar
                width={conventionalWidth}
                color="var(--series-2)"
                label="Conventional referral"
                value={metric.format(metric.conventional)}
              />
              <Bar
                width={nirantarWidth}
                color="var(--series-1)"
                label="Nirantar plan"
                value={metric.format(metric.nirantar)}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}

function Bar({
  width,
  color,
  label,
  value,
}: {
  width: number;
  color: string;
  label: string;
  value: string;
}) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
      <span
        style={{
          width: 148,
          flex: "none",
          fontSize: 11.5,
          color: "var(--text-secondary)",
        }}
      >
        {label}
      </span>
      <span
        style={{
          flex: 1,
          minWidth: 0,
          display: "flex",
          alignItems: "center",
          gap: 8,
        }}
      >
        <span
          style={{
            display: "block",
            height: 14,
            width: `${Math.max(1.5, width)}%`,
            background: color,
            borderRadius: 4,
          }}
        />
        <b style={{ fontSize: 12.5, fontVariantNumeric: "tabular-nums" }}>
          {value}
        </b>
      </span>
    </div>
  );
}

/* ------------------------------------------------------------------------ */
/* Block schematic: panchayat tiles coloured by magnitude.                   */
/* Explicitly a schematic, not a map -- no real geometry is claimed.         */
/* ------------------------------------------------------------------------ */

export function BlockSchematic({
  rows,
  onSelect,
  selected,
}: {
  rows: {
    panchayat: string;
    healthy_years_at_stake: number;
    open: number;
    breached: number;
    population: number;
    days_until_outreach: number | null;
    unstaffed_facilities: string[];
    km_to_district_hospital: number;
  }[];
  onSelect: (panchayat: string | null) => void;
  selected: string | null;
}) {
  const max = Math.max(...rows.map((row) => row.healthy_years_at_stake), 1);
  return (
    <>
      <div className="schematic">
        {rows.map((row) => {
          const isSelected = selected === row.panchayat;
          const background = seqColor(row.healthy_years_at_stake, max);
          const ink = inkOn(row.healthy_years_at_stake, max);
          const noOutreach =
            row.days_until_outreach === null || row.days_until_outreach > 14;
          return (
            <button
              key={row.panchayat}
              className="tile"
              style={{
                background,
                color: ink,
                outline: isSelected ? `2px solid var(--text-primary)` : undefined,
                outlineOffset: 2,
              }}
              onClick={() => onSelect(isSelected ? null : row.panchayat)}
              aria-pressed={isSelected}
              title={`${row.panchayat}: ${n1(row.healthy_years_at_stake)} healthy years at stake`}
            >
              {(noOutreach || row.unstaffed_facilities.length > 0) && (
                <span className="flag">
                  {row.unstaffed_facilities.length > 0 ? "no staff" : "no van"}
                </span>
              )}
              <span className="tname">{row.panchayat}</span>
              <span>
                <span className="tval">{n1(row.healthy_years_at_stake)}</span>
                <span className="tfoot" style={{ display: "block" }}>
                  healthy yrs at stake
                </span>
              </span>
              <span className="tfoot">
                {n(row.open)} open · {row.km_to_district_hospital.toFixed(0)} km to DH
              </span>
            </button>
          );
        })}
      </div>
      <ScaleRamp />
    </>
  );
}

function ScaleRamp() {
  return (
    <div className="scale-legend">
      <span>fewer healthy years at stake</span>
      <span className="ramp" aria-hidden>
        {SEQ_STEPS.map((step, index) => (
          <span key={index} style={{ background: step }} />
        ))}
      </span>
      <span>more</span>
    </div>
  );
}

/* ------------------------------------------------------------------------ */
/* Line chart with a crosshair. Two series max, one shared y-axis.          */
/* Never a second y-scale: two measures of different scale get two charts.  */
/* ------------------------------------------------------------------------ */

export type Series = {
  label: string;
  color: string;
  points: { x: number; y: number }[];
};

export function LineChart({
  series,
  yLabel,
  xLabel,
  formatY = (value: number) => n(value),
  height = 230,
}: {
  series: Series[];
  yLabel: string;
  xLabel: string;
  formatY?: (value: number) => string;
  height?: number;
}) {
  const { ref, show, hide, node } = useTooltip();
  const width = 760;
  const padLeft = 54;
  const padBottom = 30;
  const padTop = 12;
  const plotWidth = width - padLeft - 16;
  const plotHeight = height - padBottom - padTop;

  const allPoints = series.flatMap((item) => item.points);
  if (allPoints.length === 0) return null;
  const maxX = Math.max(...allPoints.map((point) => point.x), 1);
  const maxY = nice(Math.max(...allPoints.map((point) => point.y), 1));

  const sx = (x: number) => padLeft + (x / maxX) * plotWidth;
  const sy = (y: number) => padTop + plotHeight - (y / maxY) * plotHeight;

  const path = (points: { x: number; y: number }[]) =>
    points
      .map((point, index) => `${index === 0 ? "M" : "L"}${sx(point.x)},${sy(point.y)}`)
      .join(" ");

  const ticksY = [0, maxY / 2, maxY];
  const ticksX = [0, Math.round(maxX / 2), maxX];

  return (
    <div className="chart-wrap" ref={ref}>
      <svg
        className="chart"
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label={`${yLabel} over ${xLabel}, comparing ${series.map((s) => s.label).join(" and ")}`}
      >
        {ticksY.map((tick) => (
          <g key={tick}>
            <line
              className="gridline"
              x1={padLeft}
              y1={sy(tick)}
              x2={width - 16}
              y2={sy(tick)}
            />
            <text className="tick" x={padLeft - 8} y={sy(tick) + 4} textAnchor="end">
              {formatY(tick)}
            </text>
          </g>
        ))}
        {ticksX.map((tick) => (
          <text
            key={tick}
            className="tick"
            x={sx(tick)}
            y={height - padBottom + 18}
            textAnchor="middle"
          >
            {tick}
          </text>
        ))}
        <text
          className="tick"
          x={padLeft + plotWidth / 2}
          y={height - 2}
          textAnchor="middle"
        >
          {xLabel}
        </text>
        <line
          className="axisline"
          x1={padLeft}
          y1={padTop}
          x2={padLeft}
          y2={padTop + plotHeight}
        />

        {series.map((item, seriesIndex) => {
          const last = item.points[item.points.length - 1];
          // Two series can finish at almost the same value, in which case
          // their endpoint labels land on top of each other. Nudge them
          // apart rather than letting them overlap.
          const others = series
            .filter((_, index) => index !== seriesIndex)
            .map((other) => other.points[other.points.length - 1]?.y ?? 0);
          const collides = others.some(
            (value) => Math.abs(sy(value) - sy(last?.y ?? 0)) < 14,
          );
          const nudge = collides && seriesIndex > 0 ? 16 : 0;
          return (
            <g key={item.label}>
              <path
                d={path(item.points)}
                fill="none"
                stroke={item.color}
                strokeWidth={2}
                strokeLinejoin="round"
                strokeLinecap="round"
              />
              {/* Direct label at the endpoint rather than a value on every
                  point. */}
              {last && (
                <text
                  x={sx(last.x) - 4}
                  y={sy(last.y) - 8 + nudge}
                  textAnchor="end"
                  style={{ fontSize: 11.5, fontWeight: 620 }}
                  fill={item.color}
                >
                  {formatY(last.y)}
                </text>
              )}
            </g>
          );
        })}

        {/* One hit band per x position, so the hit target is far wider than
            the 2px line and a crosshair can snap to the nearest day. */}
        {Array.from({ length: Math.min(maxX + 1, 120) }, (_, index) => {
          const step = Math.max(1, Math.round((maxX + 1) / Math.min(maxX + 1, 120)));
          const xValue = index * step;
          const bandWidth = plotWidth / Math.min(maxX + 1, 120);
          return (
            <rect
              key={xValue}
              className="hit"
              x={sx(xValue) - bandWidth / 2}
              y={padTop}
              width={bandWidth}
              height={plotHeight}
              onMouseMove={(event) => {
                show(
                  {
                    title: `${xLabel} ${xValue}`,
                    rows: series.map((item) => {
                      const found =
                        item.points.find((point) => point.x === xValue) ??
                        item.points[item.points.length - 1];
                      return { k: item.label, v: formatY(found?.y ?? 0) };
                    }),
                  },
                  event,
                );
              }}
              onMouseLeave={hide}
            />
          );
        })}
      </svg>
      {node}
    </div>
  );
}

/* ------------------------------------------------------------------------ */
/* Reliability diagram: predicted versus what actually happened.            */
/* ------------------------------------------------------------------------ */

export function ReliabilityChart({
  rows,
}: {
  rows: {
    bucket: string;
    n: number;
    predicted_no_show: number;
    realised_no_show: number;
    error: number;
  }[];
}) {
  const { ref, show, hide, node } = useTooltip();
  const size = 340;
  // Left padding has to clear the tick labels *and* the rotated axis title;
  // at 42 the title overlapped the 50% tick.
  const pad = 62;
  const plot = size - pad - 16;
  const sx = (value: number) => pad + value * plot;
  const sy = (value: number) => pad + plot - value * plot;
  const maxN = Math.max(...rows.map((row) => row.n), 1);

  return (
    <div className="chart-wrap" ref={ref}>
      <svg
        className="chart"
        viewBox={`0 0 ${size} ${size}`}
        style={{ maxWidth: 380 }}
        role="img"
        aria-label="Predicted no-show against realised no-show. Points on the diagonal would mean a perfectly calibrated model."
      >
        {[0, 0.25, 0.5, 0.75, 1].map((tick) => (
          <g key={tick}>
            <line
              className="gridline"
              x1={pad}
              y1={sy(tick)}
              x2={pad + plot}
              y2={sy(tick)}
            />
            <text className="tick" x={pad - 7} y={sy(tick) + 4} textAnchor="end">
              {Math.round(tick * 100)}%
            </text>
            <text
              className="tick"
              x={sx(tick)}
              y={size - 20}
              textAnchor="middle"
            >
              {Math.round(tick * 100)}%
            </text>
          </g>
        ))}
        {/* Perfect calibration. Dashed is legitimate here: it marks a
            reference line, not a grid. */}
        <line
          x1={sx(0)}
          y1={sy(0)}
          x2={sx(1)}
          y2={sy(1)}
          stroke="var(--axis)"
          strokeWidth={1.5}
          strokeDasharray="4 4"
        />
        <text
          x={sx(0.62)}
          y={sy(0.72)}
          className="tick"
          style={{ fontSize: 10.5 }}
        >
          perfectly calibrated
        </text>

        {rows.map((row) => {
          const radius = 4 + (row.n / maxN) * 7;
          return (
            <g key={row.bucket}>
              <circle
                cx={sx(row.predicted_no_show)}
                cy={sy(row.realised_no_show)}
                r={radius}
                fill="var(--series-1)"
                stroke="var(--surface-1)"
                strokeWidth={2}
              />
              <circle
                className="hit"
                cx={sx(row.predicted_no_show)}
                cy={sy(row.realised_no_show)}
                r={Math.max(14, radius + 8)}
                onMouseMove={(event) =>
                  show(
                    {
                      title: `Predicted ${row.bucket}`,
                      rows: [
                        { k: "Contacts", v: n(row.n) },
                        { k: "Predicted", v: pct(row.predicted_no_show, 1) },
                        { k: "Actually happened", v: pct(row.realised_no_show, 1) },
                        {
                          k: "Error",
                          v: `${row.error > 0 ? "+" : ""}${pct(row.error, 1)}`,
                        },
                      ],
                    },
                    event,
                  )
                }
                onMouseLeave={hide}
              />
            </g>
          );
        })}
        <text
          className="tick"
          x={pad + plot / 2}
          y={size - 4}
          textAnchor="middle"
        >
          predicted no-show
        </text>
        <text
          className="tick"
          transform={`rotate(-90 14 ${pad + plot / 2})`}
          x={14}
          y={pad + plot / 2}
          textAnchor="middle"
        >
          realised no-show
        </text>
      </svg>
      {node}
    </div>
  );
}
