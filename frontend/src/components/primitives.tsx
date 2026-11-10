import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

/* --- card shell with a chart / table view toggle ------------------------- */

type ViewMode = "chart" | "table";
const ViewCtx = createContext<ViewMode>("chart");
export const useViewMode = () => useContext(ViewCtx);

export function Card({
  title,
  sub,
  aside,
  children,
  table,
  defaultView = "chart",
}: {
  title?: string;
  sub?: ReactNode;
  aside?: ReactNode;
  children: ReactNode;
  /** The WCAG-clean equivalent. Every chart gets one. */
  table?: ReactNode;
  defaultView?: ViewMode;
}) {
  const [view, setView] = useState<ViewMode>(defaultView);
  return (
    <section className="card">
      {(title || aside || table) && (
        <div className="card-head">
          <div style={{ minWidth: 0 }}>
            {title && <h3>{title}</h3>}
          </div>
          {aside}
          {table && (
            <div className="viewtoggle" role="group" aria-label="View as">
              <button
                aria-pressed={view === "chart"}
                onClick={() => setView("chart")}
              >
                Chart
              </button>
              <button
                aria-pressed={view === "table"}
                onClick={() => setView("table")}
              >
                Table
              </button>
            </div>
          )}
        </div>
      )}
      {sub && <p className="sub">{sub}</p>}
      <ViewCtx.Provider value={view}>
        {view === "table" && table ? table : children}
      </ViewCtx.Provider>
    </section>
  );
}

/* --- stat tile ----------------------------------------------------------- */

export function Stat({
  label,
  value,
  foot,
  tone,
  small,
}: {
  label: string;
  value: ReactNode;
  foot?: ReactNode;
  tone?: "good" | "bad";
  small?: boolean;
}) {
  return (
    <div className="card stat">
      <div className="label">{label}</div>
      <div className={small ? "value sm" : "value"}>{value}</div>
      {foot && <div className={`foot${tone ? ` ${tone}` : ""}`}>{foot}</div>}
    </div>
  );
}

/* --- tooltip ------------------------------------------------------------- */

export type TipRow = { k: string; v: string };
export type TipContent = { title: string; rows: TipRow[] } | null;

export function useTooltip() {
  const ref = useRef<HTMLDivElement>(null);
  const [tip, setTip] = useState<{
    content: TipContent;
    x: number;
    y: number;
  }>({ content: null, x: 0, y: 0 });

  const show = useCallback(
    (content: TipContent, event: { clientX: number; clientY: number }) => {
      const box = ref.current?.getBoundingClientRect();
      if (!box) return;
      setTip({
        content,
        x: event.clientX - box.left,
        y: event.clientY - box.top,
      });
    },
    [],
  );
  const hide = useCallback(() => setTip((t) => ({ ...t, content: null })), []);

  const node = tip.content ? (
    <div
      className="tooltip"
      style={{
        left: Math.max(4, Math.min(tip.x + 12, (ref.current?.clientWidth ?? 300) - 170)),
        top: Math.max(4, tip.y - 12),
      }}
      role="status"
    >
      <div className="t-title">{tip.content.title}</div>
      {tip.content.rows.map((row) => (
        <div className="t-row" key={row.k}>
          <span>{row.k}</span>
          <b>{row.v}</b>
        </div>
      ))}
    </div>
  ) : null;

  return { ref, show, hide, node };
}

/* --- legend -------------------------------------------------------------- */

export function Legend({
  items,
}: {
  items: { label: string; color: string }[];
}) {
  return (
    <div className="legend">
      {items.map((item) => (
        <span className="key" key={item.label}>
          <span className="swatch" style={{ background: item.color }} />
          {item.label}
        </span>
      ))}
    </div>
  );
}

export function ScaleLegend({
  from,
  to,
  steps,
}: {
  from: string;
  to: string;
  steps: string[];
}) {
  return (
    <div className="scale-legend">
      <span>{from}</span>
      <span className="ramp" aria-hidden>
        {steps.map((step, index) => (
          <span key={index} style={{ background: step }} />
        ))}
      </span>
      <span>{to}</span>
    </div>
  );
}

/* --- generic data table -------------------------------------------------- */

export function DataTable<Row>({
  rows,
  columns,
  caption,
}: {
  rows: Row[];
  columns: { head: string; cell: (row: Row) => ReactNode }[];
  caption?: string;
}) {
  return (
    <table className="data">
      {caption && (
        <caption
          style={{
            captionSide: "bottom",
            textAlign: "left",
            fontSize: 12,
            color: "var(--text-muted)",
            paddingTop: 8,
          }}
        >
          {caption}
        </caption>
      )}
      <thead>
        <tr>
          {columns.map((column) => (
            <th key={column.head}>{column.head}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row, index) => (
          <tr key={index}>
            {columns.map((column) => (
              <td key={column.head}>{column.cell(row)}</td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/* --- async data loading -------------------------------------------------- */

export function Loading({ lines = 3 }: { lines?: number }) {
  const widths = useMemo(
    () => Array.from({ length: lines }, (_, index) => 95 - index * 14),
    [lines],
  );
  return (
    <div style={{ display: "grid", gap: 9, padding: "8px 0" }}>
      {widths.map((width, index) => (
        <div className="skeleton" key={index} style={{ width: `${width}%` }} />
      ))}
    </div>
  );
}

export function ErrorNote({ error }: { error: unknown }) {
  const message =
    error instanceof Error ? error.message : "Something went wrong.";
  return (
    <div className="banner" role="alert">
      <span aria-hidden>⚠</span>
      <div>
        <strong>Could not load this.</strong> {message}
      </div>
    </div>
  );
}
