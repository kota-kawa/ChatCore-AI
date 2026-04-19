type InlineLoadingProps = {
  label: string;
  className?: string;
};

function joinClasses(...classes: Array<string | undefined>) {
  return classes.filter(Boolean).join(" ");
}

export function InlineLoading({ label, className }: InlineLoadingProps) {
  return (
    <div className={joinClasses("cc-inline-loading", className)} role="status" aria-live="polite">
      <svg
        aria-hidden="true"
        className="cc-inline-loading__spinner"
        viewBox="0 0 24 24"
        fill="none"
      >
        <circle cx="12" cy="12" r="9" stroke="currentColor" strokeOpacity="0.2" strokeWidth="3" />
        <path
          d="M21 12a9 9 0 0 0-9-9"
          stroke="currentColor"
          strokeWidth="3"
          strokeLinecap="round"
        />
      </svg>
      <span>{label}</span>
    </div>
  );
}
