import AsyncStorage from '@react-native-async-storage/async-storage';

// The site's static JSON feed (built by touchline_takes/web/api.py).
export const API_BASE = process.env.EXPO_PUBLIC_API_BASE ?? 'https://touchlinetakes.com/api/v1';

export type ArticleSummary = {
  slug: string;
  title: string;
  teaser: string;
  type: string;
  league: string;
  teams: string[];
  published_at: string;
  sources: number;
  url: string;
};

export type Paragraph = { text: string; cites: string[]; verdict: boolean };

export type Evidence = { id: string; kind: string; source: string; text: string; url: string };

export type Article = ArticleSummary & { paragraphs: Paragraph[]; evidence: Evidence[] };

export type Club = { slug: string; name: string; league: string; articles: number };

const CACHE_PREFIX = 'cache:';

/** Fetch a feed file; on success keep a copy so the app still works offline. */
async function getJson<T>(path: string): Promise<{ data: T; offline: boolean }> {
  const key = CACHE_PREFIX + path;
  try {
    const response = await fetch(`${API_BASE}/${path}`, { headers: { Accept: 'application/json' } });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = (await response.json()) as T;
    AsyncStorage.setItem(key, JSON.stringify(data)).catch(() => undefined);
    return { data, offline: false };
  } catch (error) {
    const cached = await AsyncStorage.getItem(key);
    if (cached) return { data: JSON.parse(cached) as T, offline: true };
    throw error;
  }
}

export async function fetchArticles() {
  const { data, offline } = await getJson<{ articles: ArticleSummary[] }>('articles.json');
  return { articles: data.articles, offline };
}

export async function fetchClubs() {
  const { data, offline } = await getJson<{ clubs: Club[] }>('clubs.json');
  return { clubs: data.clubs, offline };
}

export async function fetchArticle(slug: string) {
  const { data, offline } = await getJson<Article>(`article/${encodeURIComponent(slug)}.json`);
  return { article: data, offline };
}

/** "19 Nov" from an ISO timestamp. */
export function shortDate(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso.slice(0, 10);
  return date.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' });
}

/** "explainer" -> "Explainer", "match_report" -> "Match report". */
export function typeLabel(type: string): string {
  const words = type.replace(/_/g, ' ');
  return words.charAt(0).toUpperCase() + words.slice(1);
}
