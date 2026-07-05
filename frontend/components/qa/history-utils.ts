import type { SessionSummary } from "@/lib/types";

export type HistoryGroup = "today" | "week" | "older";

export interface GroupedSessions {
  today: SessionSummary[];
  week: SessionSummary[];
  older: SessionSummary[];
}

const TAG_STYLES = [
  "bg-violet-100 text-violet-700",
  "bg-blue-100 text-blue-700",
  "bg-orange-100 text-orange-700",
  "bg-emerald-100 text-emerald-700",
  "bg-accent-soft text-accent-soft-foreground",
] as const;

/** Pick a stable pastel tag style from the label text. */
export function tagStyleFor(label: string): string {
  let hash = 0;
  for (let i = 0; i < label.length; i += 1) {
    hash = (hash * 31 + label.charCodeAt(i)) | 0;
  }
  return TAG_STYLES[Math.abs(hash) % TAG_STYLES.length];
}

/** Primary scope label: first selected tag, else knowledge-base name. */
export function sessionTagLabel(session: SessionSummary): string | null {
  const sf = session.scope_filter as { tags?: string[]; kb_names?: string[] } | null | undefined;
  const tag = sf?.tags?.[0];
  if (tag) return tag;
  if (session.kb_name && session.kb_name !== "default") return session.kb_name;
  const kb = sf?.kb_names?.[0];
  return kb ?? null;
}

function sessionInstant(session: SessionSummary): Date | null {
  const raw = session.updated_at ?? session.created_at;
  if (!raw) return null;
  const d = new Date(raw);
  return Number.isNaN(d.getTime()) ? null : d;
}

function startOfLocalDay(d: Date): Date {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate());
}

/** Bucket sessions for the history drawer (today / past 7 days / older). */
export function groupSessions(sessions: SessionSummary[]): GroupedSessions {
  const now = new Date();
  const todayStart = startOfLocalDay(now).getTime();
  const weekStart = todayStart - 6 * 24 * 60 * 60 * 1000;

  const out: GroupedSessions = { today: [], week: [], older: [] };
  for (const s of sessions) {
    const d = sessionInstant(s);
    if (!d) {
      out.older.push(s);
      continue;
    }
    const t = d.getTime();
    if (t >= todayStart) out.today.push(s);
    else if (t >= weekStart) out.week.push(s);
    else out.older.push(s);
  }
  return out;
}

/** Filter sessions by title (client-side search). */
export function filterSessions(sessions: SessionSummary[], query: string): SessionSummary[] {
  const q = query.trim().toLowerCase();
  if (!q) return sessions;
  return sessions.filter((s) => {
    const title = (s.title || s.session_id).toLowerCase();
    const tag = sessionTagLabel(s)?.toLowerCase() ?? "";
    return title.includes(q) || tag.includes(q);
  });
}

interface FormatTimeOpts {
  locale: string;
  todayLabel: (d: Date) => string;
  daysAgo: (count: number) => string;
}

/** Relative timestamp aligned with the history drawer mock (time today, days ago this week). */
export function formatHistoryTime(
  iso: string | null | undefined,
  { locale, todayLabel, daysAgo }: FormatTimeOpts,
): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;

  const now = new Date();
  const todayStart = startOfLocalDay(now).getTime();
  const t = d.getTime();

  if (t >= todayStart) {
    return todayLabel(d);
  }

  const dayMs = 24 * 60 * 60 * 1000;
  const days = Math.floor((todayStart - startOfLocalDay(d).getTime()) / dayMs);
  if (days >= 1 && days <= 7) {
    return daysAgo(days);
  }

  return d.toLocaleDateString(locale, { month: "short", day: "numeric" });
}
