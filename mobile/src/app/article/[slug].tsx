import Ionicons from '@expo/vector-icons/Ionicons';
import { useLocalSearchParams } from 'expo-router';
import * as WebBrowser from 'expo-web-browser';
import { useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, ScrollView, Text, View } from 'react-native';

import { Notice, Tag } from '../../components/ui';
import { fetchArticle, shortDate, typeLabel, type Article } from '../../lib/api';
import { useStore } from '../../lib/store';
import { fonts, useColors } from '../../lib/theme';

export default function ArticleScreen() {
  const c = useColors();
  const { slug } = useLocalSearchParams<{ slug: string }>();
  const { isFollowing, toggleFollow } = useStore();
  const [article, setArticle] = useState<Article | null>(null);
  const [offline, setOffline] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    fetchArticle(String(slug))
      .then((r) => { if (live) { setArticle(r.article); setOffline(r.offline); } })
      .catch(() => { if (live) setError("Couldn't load this take. Check your connection and try again."); });
    return () => { live = false; };
  }, [slug]);

  if (error) return <View style={{ flex: 1, padding: 16, backgroundColor: c.page }}><Notice text={error} /></View>;
  if (!article) {
    return <View style={{ flex: 1, justifyContent: 'center', backgroundColor: c.page }}><ActivityIndicator color={c.maroon} /></View>;
  }

  const open = (url: string) => { if (url) WebBrowser.openBrowserAsync(url); };

  return (
    <ScrollView style={{ backgroundColor: c.page }} contentContainerStyle={{ padding: 18, paddingBottom: 48, gap: 14 }}>
      {offline ? <Notice text="You're offline. This is the copy saved on this phone." /> : null}
      <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 6 }}>
        <Tag label={typeLabel(article.type)} tone={article.type === 'match_report' ? 'maroon' : article.type === 'preview' ? 'gold' : 'teal'} />
        {article.league ? <Tag label={article.league} /> : null}
      </View>
      <Text style={{ fontFamily: fonts.heavy, fontSize: 28, lineHeight: 33, color: c.maroon }}>{article.title}</Text>
      <Text style={{ fontFamily: fonts.regular, fontSize: 13, color: c.muted }}>
        Published {shortDate(article.published_at)} by the Touchline Takes newsroom
      </Text>

      {article.teams.length ? (
        <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8 }}>
          {article.teams.map((team) => {
            const on = isFollowing(team);
            return (
              <Pressable key={team} onPress={() => toggleFollow(team)} accessibilityRole="switch"
                accessibilityState={{ checked: on }}
                style={{ flexDirection: 'row', alignItems: 'center', gap: 6, paddingVertical: 6, paddingHorizontal: 10,
                  borderRadius: 2, borderWidth: 1.5, borderColor: c.maroon, backgroundColor: on ? c.maroon : 'transparent' }}>
                <Ionicons name={on ? 'star' : 'star-outline'} size={14} color={on ? c.gold : c.maroon} />
                <Text style={{ fontFamily: fonts.bold, fontSize: 13, color: on ? c.onDark : c.maroon }}>
                  {on ? `Following ${team}` : `Follow ${team}`}
                </Text>
              </Pressable>
            );
          })}
        </View>
      ) : null}

      {article.paragraphs.map((p, i) => (
        <View key={i} style={p.verdict ? { borderLeftWidth: 5, borderLeftColor: c.gold, backgroundColor: c.card, padding: 14 } : undefined}>
          <Text style={{ fontFamily: p.verdict ? fonts.bold : fonts.regular, fontSize: 17, lineHeight: 26, color: p.verdict ? c.maroon : c.ink }}>
            {p.text}
            {p.cites.map((id) => (
              <Text key={id} style={{ fontFamily: fonts.bold, fontSize: 11, color: c.maroon }}>{` ${id}`}</Text>
            ))}
          </Text>
        </View>
      ))}

      <View style={{ borderTopWidth: 2, borderTopColor: c.line, paddingTop: 14, marginTop: 8, gap: 10 }}>
        <Text style={{ fontFamily: fonts.bold, fontSize: 13, letterSpacing: 1.6, color: c.maroon }}>SOURCES & DATA</Text>
        {article.evidence.map((e) => (
          <View key={e.id} style={{ flexDirection: 'row', gap: 10 }}>
            <Text style={{ fontFamily: fonts.heavy, fontSize: 13, color: c.maroon, width: 34 }}>{e.id}</Text>
            <View style={{ flex: 1 }}>
              {e.kind === 'story' ? (
                <Text style={{ fontFamily: fonts.regular, fontSize: 14, color: c.ink }}>
                  {e.source}
                  {e.url ? ': ' : ''}
                  {e.url ? (
                    <Text onPress={() => open(e.url)} accessibilityRole="link"
                      style={{ color: c.maroon, textDecorationLine: 'underline' }}>
                      read the original report
                    </Text>
                  ) : null}
                </Text>
              ) : (
                <Text style={{ fontFamily: fonts.regular, fontSize: 14, color: c.ink }}>
                  <Text style={{ color: c.muted }}>{e.source}: </Text>{e.text}
                </Text>
              )}
            </View>
          </View>
        ))}
      </View>

      <Pressable onPress={() => open(article.url)} style={{ paddingVertical: 10 }}>
        <Text style={{ fontFamily: fonts.bold, fontSize: 15, color: c.maroon, textDecorationLine: 'underline' }}>
          Read on touchlinetakes.com
        </Text>
      </Pressable>
    </ScrollView>
  );
}
