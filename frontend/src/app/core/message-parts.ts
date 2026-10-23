export interface MessagePart {
  text: string;
  url?: string;
}

/** Split plain provider text into safe Angular text nodes and HTTP(S) links. */
export function messageParts(content: unknown): MessagePart[] {
  const text = String(content ?? '');
  const result: MessagePart[] = [];
  const pattern = /https?:\/\/[^\s<>]+/gi;
  let cursor = 0;
  for (const match of text.matchAll(pattern)) {
    const index = match.index ?? 0;
    if (index > cursor) result.push({ text: text.slice(cursor, index) });
    const raw = match[0];
    const url = raw.replace(/[),.;!?]+$/, '');
    result.push({ text: url, url });
    if (url.length < raw.length) result.push({ text: raw.slice(url.length) });
    cursor = index + raw.length;
  }
  if (cursor < text.length) result.push({ text: text.slice(cursor) });
  return result.length ? result : [{ text }];
}

