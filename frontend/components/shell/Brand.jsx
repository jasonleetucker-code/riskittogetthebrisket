import Link from "next/link";

/** One wordmark for the desktop and mobile broadcast mastheads. */
export default function Brand({ compact = false }) {
  return (
    <Link
      href="/"
      className={`shell-brand${compact ? " shell-brand--compact" : ""}`}
      aria-label="Chase Upside"
    >
      <span className="shell-brand-mark" aria-hidden="true">
        CU<span className="shell-brand-arrow">↗</span>
      </span>
      <span className="shell-brand-wordmark" aria-hidden="true">
        <span>Chase</span>
        <span>
          Upside<span className="shell-brand-dot">.</span>
        </span>
      </span>
    </Link>
  );
}
