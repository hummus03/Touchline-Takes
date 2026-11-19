import AsyncStorage from '@react-native-async-storage/async-storage';
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';

import { fetchArticles, fetchClubs, type ArticleSummary, type Club } from './api';

// Followed clubs and "last seen" live only on this phone: no accounts, nothing sent to us.
const FOLLOWS_KEY = 'follows:v1';
const SEEN_KEY = 'my-clubs-seen-at:v1';

type Store = {
  articles: ArticleSummary[];
  clubs: Club[];
  loading: boolean;
  offline: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  follows: string[]; // club names, as they appear in article.teams
  isFollowing: (club: string) => boolean;
  toggleFollow: (club: string) => void;
  myArticles: ArticleSummary[];
  newForMe: number;
  seenAt: string;
  markSeen: () => void;
};

const StoreContext = createContext<Store | null>(null);

export function StoreProvider({ children }: { children: ReactNode }) {
  const [articles, setArticles] = useState<ArticleSummary[]>([]);
  const [clubs, setClubs] = useState<Club[]>([]);
  const [loading, setLoading] = useState(true);
  const [offline, setOffline] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [follows, setFollows] = useState<string[]>([]);
  const [seenAt, setSeenAt] = useState('');

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [a, c] = await Promise.all([fetchArticles(), fetchClubs()]);
      setArticles(a.articles);
      setClubs(c.clubs);
      setOffline(a.offline || c.offline);
      setError(null);
    } catch {
      setError("Couldn't reach Touchline Takes. Check your connection and pull to refresh.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    (async () => {
      const [saved, seen] = await Promise.all([
        AsyncStorage.getItem(FOLLOWS_KEY),
        AsyncStorage.getItem(SEEN_KEY),
      ]);
      if (saved) setFollows(JSON.parse(saved) as string[]);
      setSeenAt(seen ?? new Date().toISOString());
      if (!seen) AsyncStorage.setItem(SEEN_KEY, new Date().toISOString()).catch(() => undefined);
    })();
    refresh();
  }, [refresh]);

  const toggleFollow = useCallback((club: string) => {
    setFollows((current) => {
      const next = current.includes(club) ? current.filter((c) => c !== club) : [...current, club].sort();
      AsyncStorage.setItem(FOLLOWS_KEY, JSON.stringify(next)).catch(() => undefined);
      return next;
    });
  }, []);

  const markSeen = useCallback(() => {
    const now = new Date().toISOString();
    setSeenAt(now);
    AsyncStorage.setItem(SEEN_KEY, now).catch(() => undefined);
  }, []);

  const value = useMemo<Store>(() => {
    const followed = new Set(follows);
    const myArticles = articles.filter((a) => a.teams.some((t) => followed.has(t)));
    return {
      articles, clubs, loading, offline, error, refresh, follows,
      isFollowing: (club) => followed.has(club),
      toggleFollow, myArticles,
      newForMe: seenAt ? myArticles.filter((a) => a.published_at > seenAt).length : 0,
      seenAt, markSeen,
    };
  }, [articles, clubs, loading, offline, error, refresh, follows, toggleFollow, seenAt, markSeen]);

  return <StoreContext.Provider value={value}>{children}</StoreContext.Provider>;
}

export function useStore(): Store {
  const store = useContext(StoreContext);
  if (!store) throw new Error('useStore must be used inside <StoreProvider>');
  return store;
}
