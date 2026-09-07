import Link from "next/link";

type BrandProps = {
  compact?: boolean;
  inverse?: boolean;
};

export function Brand({ compact = false, inverse = false }: BrandProps) {
  return (
    <Link
      href="/"
      aria-label="Svara home"
      style={{ display: "inline-flex", alignItems: "center", gap: 10, color: inverse ? "#fbfaf7" : "inherit" }}
    >
      <svg aria-hidden="true" width="26" height="26" viewBox="0 0 26 26" fill="none">
        <circle cx="13" cy="13" r="12.25" stroke="currentColor" strokeOpacity="0.22" />
        <path d="M6.7 13c2.8 0 3.2-4.7 6.3-4.7s3.5 4.7 6.3 4.7c-2.8 0-3.2 4.7-6.3 4.7S9.5 13 6.7 13Z" fill="currentColor" />
        <circle cx="13" cy="13" r="1.75" fill="#df5f3f" />
      </svg>
      {!compact && (
        <span style={{ fontWeight: 720, fontSize: "1.02rem", letterSpacing: "-0.025em" }}>svara</span>
      )}
    </Link>
  );
}
