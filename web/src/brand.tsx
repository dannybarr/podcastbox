/** DB Labs wordmark. The flask is the A. Ink, blue, and lime only.
 * Styles live on the mark.
 */

const wordmarkCss = `
.db-wordmark{display:inline-flex;align-items:center;height:22px;flex-shrink:0;font-family:Inter,"Open Sans",sans-serif;font-weight:900;font-size:18px;letter-spacing:-0.04em;line-height:1}
.db-ink{color:var(--palette-default-text,#0F0C08)}
.db-blue{color:#2B3FD6}
.dark .db-blue{color:#7C8CF0}
.db-flask{display:inline-flex;width:0.62em;height:0.78em;margin-inline:0.02em;color:var(--palette-default-text,#0F0C08)}
.db-flask svg{width:100%;height:100%}
`;

export function FlaskMark({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 100 120" aria-hidden="true">
      <path
        d="M40 9 H60 M44 13 V39 L73.5 90.5 Q78.5 100.5 67.5 105 H32.5 Q21.5 100.5 26.5 90.5 L56 39 V13"
        fill="none"
        stroke="currentColor"
        strokeWidth="7"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path d="M37 74.5 L63 74.5 L71.5 90.5 Q75 98 67 101 H33 Q25 98 28.5 90.5 Z" fill="#BFD62F" />
    </svg>
  );
}

export function DbWordmark({ label = "DB Labs" }: { label?: string }) {
  return (
    <span className="db-wordmark" role="img" aria-label={label}>
      <style>{wordmarkCss}</style>
      <span className="db-ink">DB</span>
      <span className="db-blue">L</span>
      <span className="db-flask">
        <FlaskMark />
      </span>
      <span className="db-blue">BS</span>
    </span>
  );
}
