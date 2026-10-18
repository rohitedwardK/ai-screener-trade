import type { ReactNode } from "react";

const DISCLAIMER = "Research and decision-support only. Not financial advice.";

function renderInline(text: string, keyPrefix: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  const re = /(\*\*[^*]+\*\*|\*[^*]+\*|_([^_]+)_)/g;
  let last = 0;
  let match: RegExpExecArray | null;
  let i = 0;
  while ((match = re.exec(text)) !== null) {
    if (match.index > last) {
      nodes.push(text.slice(last, match.index));
    }
    const token = match[0];
    if (token.startsWith("**") && token.endsWith("**")) {
      nodes.push(
        <strong key={`${keyPrefix}-b-${i}`}>{token.slice(2, -2)}</strong>,
      );
    } else if (token.startsWith("*") && token.endsWith("*")) {
      nodes.push(<em key={`${keyPrefix}-i-${i}`}>{token.slice(1, -1)}</em>);
    } else if (token.startsWith("_") && token.endsWith("_")) {
      nodes.push(<em key={`${keyPrefix}-u-${i}`}>{token.slice(1, -1)}</em>);
    } else {
      nodes.push(token);
    }
    last = match.index + token.length;
    i += 1;
  }
  if (last < text.length) nodes.push(text.slice(last));
  return nodes;
}

function headingLevel(line: string): { level: 1 | 2 | 3; text: string } | null {
  const m = /^(#{1,3})\s+(.*)$/.exec(line);
  if (!m) return null;
  const level = m[1].length as 1 | 2 | 3;
  return { level, text: m[2] };
}

function isBullet(line: string): string | null {
  const m = /^[-*]\s+(.*)$/.exec(line);
  return m ? m[1] : null;
}

/** First readable sentence from a briefing, skipping headings and the disclaimer. */
export function briefingExcerpt(md: string | null | undefined, maxLen = 180): string | null {
  if (!md) return null;
  for (const raw of md.split("\n")) {
    const line = raw.trim();
    if (!line || line.startsWith("#")) continue;
    if (line.includes(DISCLAIMER)) continue;
    const bullet = isBullet(line);
    const plain = (bullet ?? line)
      .replace(/\*\*/g, "")
      .replace(/^[_*]|[_*]$/g, "")
      .replace(/^\*\*[^*]+\*\*\.?\s*/, "");
    if (!plain) continue;
    if (plain.length <= maxLen) return plain;
    return `${plain.slice(0, maxLen - 1).trimEnd()}…`;
  }
  return null;
}

export function humanEnumLabel(value: string | null | undefined): string {
  if (!value) return "—";
  return value
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1).toLowerCase())
    .join("-");
}

export function BriefingMarkdown({ source }: { source: string }) {
  const lines = source.replace(/\r\n/g, "\n").split("\n");
  const blocks: ReactNode[] = [];
  let bullets: string[] = [];
  let key = 0;

  const flushBullets = () => {
    if (bullets.length === 0) return;
    const items = bullets;
    bullets = [];
    blocks.push(
      <ul key={`ul-${key}`} className="list-disc pl-5 space-y-1 my-2">
        {items.map((item, idx) => (
          <li key={`li-${key}-${idx}`}>{renderInline(item, `li-${key}-${idx}`)}</li>
        ))}
      </ul>,
    );
    key += 1;
  };

  for (const raw of lines) {
    const line = raw.trimEnd();
    const trimmed = line.trim();
    if (!trimmed) {
      flushBullets();
      continue;
    }
    const bullet = isBullet(trimmed);
    if (bullet != null) {
      bullets.push(bullet);
      continue;
    }
    flushBullets();
    const heading = headingLevel(trimmed);
    if (heading) {
      const cls = heading.level === 1 ? "text-base font-semibold mt-1 mb-2" : "text-sm font-semibold mt-3 mb-1";
      const Tag = heading.level === 3 ? "h4" : "h3";
      blocks.push(
        <Tag key={`h-${key}`} className={cls}>
          {renderInline(heading.text, `h-${key}`)}
        </Tag>,
      );
      key += 1;
      continue;
    }
    blocks.push(
      <p key={`p-${key}`} className="my-1.5 leading-relaxed">
        {renderInline(trimmed, `p-${key}`)}
      </p>,
    );
    key += 1;
  }
  flushBullets();

  return <div className="text-sm text-fg">{blocks}</div>;
}
