/**
 * Small building blocks for the integrated pages. They reuse the existing
 * ShiftGuard classes (surface, filter-tabs, member-drawer, status-pill,
 * primary/secondary buttons...) so new pages match the original design.
 */
import type { ReactNode } from "react";
import { AlertCircle, Loader2, X } from "lucide-react";

export function PageHeader({
  kicker,
  title,
  description,
  actions,
}: {
  kicker: string;
  title: string;
  description?: string;
  actions?: ReactNode;
}) {
  return (
    <section className="manager-title-row">
      <div>
        <span className="section-kicker">{kicker}</span>
        <h1>{title}</h1>
        {description && <p>{description}</p>}
      </div>
      {actions && <div className="manager-controls">{actions}</div>}
    </section>
  );
}

export function Panel({
  kicker,
  title,
  actions,
  children,
  className = "",
}: {
  kicker?: string;
  title?: string;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`surface pp-panel ${className}`}>
      {(title || actions) && (
        <div className="surface-heading">
          <div>
            {kicker && <span className="section-kicker">{kicker}</span>}
            {title && <h2>{title}</h2>}
          </div>
          {actions && <div className="pp-actions">{actions}</div>}
        </div>
      )}
      {children}
    </section>
  );
}

export function Tabs<T extends string>({
  tabs,
  value,
  onChange,
}: {
  tabs: ReadonlyArray<{ id: T; label: string }>;
  value: T;
  onChange: (value: T) => void;
}) {
  return (
    <div className="filter-tabs pp-tabs" role="tablist">
      {tabs.map((tab) => (
        <button
          key={tab.id}
          role="tab"
          aria-selected={value === tab.id}
          className={value === tab.id ? "active" : ""}
          onClick={() => onChange(tab.id)}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}

export type Tone = "danger" | "warning" | "healthy" | "info" | "neutral";

export function Pill({ tone, children }: { tone: Tone; children: ReactNode }) {
  return <span className={`status-pill ${tone}`}>{children}</span>;
}

export function Loading({ text = "Loading…" }: { text?: string }) {
  return (
    <div className="pp-state">
      <Loader2 size={18} className="pp-spin" />
      {text}
    </div>
  );
}

export function ErrorNote({ message, onRetry }: { message: string | null; onRetry?: () => void }) {
  if (!message) return null;
  return (
    <div className="pp-error" role="alert">
      <AlertCircle size={16} />
      <span>{message}</span>
      {onRetry && (
        <button className="secondary-button" onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  );
}

export function SuccessNote({ message }: { message: string | null }) {
  if (!message) return null;
  return <div className="pp-success">{message}</div>;
}

export function Empty({ text }: { text: string }) {
  return <div className="pp-state">{text}</div>;
}

/** Async-data wrapper: shows loading / error / children. */
export function AsyncBlock({
  loading,
  error,
  onRetry,
  children,
}: {
  loading: boolean;
  error: string | null;
  onRetry?: () => void;
  children: ReactNode;
}) {
  if (error) return <ErrorNote message={error} onRetry={onRetry} />;
  if (loading) return <Loading />;
  return <>{children}</>;
}

export interface Column<T> {
  header: string;
  render: (row: T) => ReactNode;
  width?: string;
}

export function DataTable<T>({
  columns,
  rows,
  rowKey,
  empty = "Nothing here yet.",
  onRowClick,
}: {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  empty?: string;
  onRowClick?: (row: T) => void;
}) {
  if (!rows.length) return <Empty text={empty} />;
  const template = columns.map((c) => c.width ?? "minmax(0, 1fr)").join(" ");
  return (
    <div className="pp-table" role="table">
      <div className="pp-row pp-head" role="row" style={{ gridTemplateColumns: template }}>
        {columns.map((c) => (
          <span key={c.header} role="columnheader">
            {c.header}
          </span>
        ))}
      </div>
      {rows.map((row) => (
        <div
          key={rowKey(row)}
          role="row"
          className={`pp-row ${onRowClick ? "clickable" : ""}`}
          style={{ gridTemplateColumns: template }}
          onClick={onRowClick ? () => onRowClick(row) : undefined}
        >
          {columns.map((c) => (
            <div key={c.header} role="cell" className="pp-cell" data-label={c.header}>
              {c.render(row)}
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

/** Slide-in side panel (same look as the team member drawer) used for forms. */
export function SidePanel({
  open,
  kicker,
  title,
  onClose,
  children,
}: {
  open: boolean;
  kicker: string;
  title: string;
  onClose: () => void;
  children: ReactNode;
}) {
  if (!open) return null;
  return (
    <>
      <button className="drawer-backdrop" aria-label="Close panel" onClick={onClose} />
      <aside className="member-drawer pp-side-panel">
        <div className="drawer-top">
          <div>
            <span className="section-kicker">{kicker}</span>
            <h2>{title}</h2>
          </div>
          <button className="ghost-icon" onClick={onClose} aria-label="Close">
            <X size={20} />
          </button>
        </div>
        {children}
      </aside>
    </>
  );
}

// ---------------------------------------------------------------------------
// form fields
// ---------------------------------------------------------------------------
interface FieldProps {
  label: string;
  hint?: string;
  full?: boolean;
}

export function TextField({
  label,
  hint,
  full,
  value,
  onChange,
  type = "text",
  required,
  placeholder,
  autoComplete,
  min,
  step,
}: FieldProps & {
  value: string | number | null | undefined;
  onChange: (value: string) => void;
  type?: string;
  required?: boolean;
  placeholder?: string;
  autoComplete?: string;
  min?: string | number;
  step?: string | number;
}) {
  return (
    <label className={`pp-field ${full ? "full" : ""}`}>
      <span>
        {label}
        {required && <em> *</em>}
      </span>
      <input
        type={type}
        value={value ?? ""}
        required={required}
        placeholder={placeholder}
        autoComplete={autoComplete}
        min={min}
        step={step}
        onChange={(e) => onChange(e.target.value)}
      />
      {hint && <small>{hint}</small>}
    </label>
  );
}

export function TextArea({
  label,
  hint,
  full = true,
  value,
  onChange,
  rows = 3,
}: FieldProps & { value: string | null | undefined; onChange: (value: string) => void; rows?: number }) {
  return (
    <label className={`pp-field ${full ? "full" : ""}`}>
      <span>{label}</span>
      <textarea rows={rows} value={value ?? ""} onChange={(e) => onChange(e.target.value)} />
      {hint && <small>{hint}</small>}
    </label>
  );
}

export function SelectField({
  label,
  hint,
  full,
  value,
  onChange,
  options,
  required,
  placeholder,
}: FieldProps & {
  value: string | null | undefined;
  onChange: (value: string) => void;
  options: ReadonlyArray<{ value: string; label: string }>;
  required?: boolean;
  placeholder?: string;
}) {
  return (
    <label className={`pp-field ${full ? "full" : ""}`}>
      <span>
        {label}
        {required && <em> *</em>}
      </span>
      <select value={value ?? ""} required={required} onChange={(e) => onChange(e.target.value)}>
        {placeholder !== undefined && <option value="">{placeholder}</option>}
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
      {hint && <small>{hint}</small>}
    </label>
  );
}

export function CheckField({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (value: boolean) => void;
}) {
  return (
    <label className="pp-check">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      <span>{label}</span>
    </label>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export const enumOptions = (values: readonly string[], format: (v: string) => string) =>
  values.map((v) => ({ value: v, label: format(v) }));
