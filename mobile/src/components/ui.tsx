import { router } from 'expo-router';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { shortDate, typeLabel, type ArticleSummary } from '../lib/api';
import { fonts, useColors, type Colors } from '../lib/theme';

/** The T-and-ball icon, drawn with views (same shapes as the site's favicon). */
export function LogoIcon({ size = 36 }: { size?: number }) {
  const c = useColors();
  const k = size / 64;
  const box = (x: number, y: number, w: number, h: number) => ({
    position: 'absolute' as const, left: x * k, top: y * k, width: w * k, height: h * k,
  });
  return (
    <View style={{ width: size, height: size, borderRadius: 12 * k, borderWidth: Math.max(1, 2 * k),
      borderColor: '#6E1A2A', backgroundColor: '#FAF4E8', overflow: 'hidden' }}>
      <View style={[box(11, 8.5, 40, 10), { backgroundColor: '#6E1A2A' }]} />
      <View style={[box(26, 8.5, 10, 38), { backgroundColor: '#6E1A2A' }]} />
      <View style={[box(39, 34.5, 12, 12), { backgroundColor: c.gold, borderRadius: 6 * k }]} />
      <View style={[box(8, 50.5, 46, 4), { backgroundColor: '#CDAAAC', borderRadius: 2 * k }]} />
    </View>
  );
}

/** "Touchline Takes" in script with the gold touchline under it. */
export function Wordmark({ size = 28 }: { size?: number }) {
  const c = useColors();
  return (
    <View style={styles.wordmarkRow}>
      <LogoIcon size={size * 1.25} />
      <View>
        <Text style={{ fontFamily: fonts.script, fontSize: size, color: c.maroon, lineHeight: size * 1.25 }}>
          Touchline Takes
        </Text>
        <View style={{ height: 3, backgroundColor: c.gold, borderRadius: 2, marginTop: -2,
          transform: [{ rotate: '-1.5deg' }] }} />
      </View>
    </View>
  );
}

export function Tag({ label, tone = 'plain' }: { label: string; tone?: 'plain' | 'teal' | 'maroon' | 'gold' }) {
  const c = useColors();
  const bg = { plain: c.sandDeep, teal: c.teal, maroon: c.maroon, gold: c.gold }[tone];
  const fg = tone === 'plain' ? c.ink : tone === 'gold' ? '#2B1A10' : c.onDark;
  return (
    <View style={[styles.tag, { backgroundColor: bg }]}>
      <Text style={[styles.tagText, { color: fg }]}>{label.toUpperCase()}</Text>
    </View>
  );
}

function typeTone(type: string): 'teal' | 'maroon' | 'gold' {
  return type === 'match_report' ? 'maroon' : type === 'preview' ? 'gold' : 'teal';
}

export function ArticleCard({ article, lead = false, isNew = false }:
  { article: ArticleSummary; lead?: boolean; isNew?: boolean }) {
  const c = useColors();
  const s = cardStyles(c);
  return (
    <Pressable
      onPress={() => router.push({ pathname: '/article/[slug]', params: { slug: article.slug } })}
      style={({ pressed }) => [s.card, lead && s.lead, pressed && { opacity: 0.85 }]}
      accessibilityRole="link" accessibilityLabel={article.title}>
        <View style={styles.tags}>
          <Tag label={typeLabel(article.type)} tone={typeTone(article.type)} />
          {article.league ? <Tag label={article.league} /> : null}
          {isNew ? <Tag label="New" tone="gold" /> : null}
        </View>
        <Text style={[s.title, lead && s.leadTitle]}>{article.title}</Text>
        <Text style={s.teaser} numberOfLines={lead ? 4 : 3}>{article.teaser}</Text>
        <Text style={s.meta}>
          {shortDate(article.published_at)} · {article.sources} source{article.sources === 1 ? '' : 's'}
          {article.teams.length ? ` · ${article.teams.join(', ')}` : ''}
        </Text>
    </Pressable>
  );
}

export function SectionTitle({ children }: { children: string }) {
  const c = useColors();
  return (
    <View style={styles.sectionRow}>
      <View style={{ width: 16, height: 16, backgroundColor: c.gold, borderTopLeftRadius: 16 }} />
      <Text style={{ fontFamily: fonts.bold, fontSize: 13, letterSpacing: 1.8, color: c.maroon }}>
        {children.toUpperCase()}
      </Text>
    </View>
  );
}

export function Notice({ text }: { text: string }) {
  const c = useColors();
  return (
    <View style={{ backgroundColor: c.card, borderLeftWidth: 4, borderLeftColor: c.gold, padding: 12, marginBottom: 12 }}>
      <Text style={{ fontFamily: fonts.regular, color: c.ink, fontSize: 14 }}>{text}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  wordmarkRow: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  tag: { paddingHorizontal: 7, paddingVertical: 3, borderRadius: 2 },
  tagText: { fontFamily: fonts.bold, fontSize: 10.5, letterSpacing: 0.8 },
  tags: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  sectionRow: { flexDirection: 'row', alignItems: 'center', gap: 8, marginBottom: 12, marginTop: 4 },
});

const cardStyles = (c: Colors) => StyleSheet.create({
  card: { backgroundColor: c.card, borderColor: c.line, borderWidth: 1, borderTopWidth: 4,
    borderTopColor: c.sandDeep, borderRadius: 4, padding: 16, marginBottom: 12, gap: 8 },
  lead: { borderTopWidth: 6, borderTopColor: c.maroon },
  title: { fontFamily: fonts.heavy, fontSize: 19, lineHeight: 24, color: c.maroon },
  leadTitle: { fontSize: 24, lineHeight: 29 },
  teaser: { fontFamily: fonts.regular, fontSize: 15, lineHeight: 22, color: c.ink },
  meta: { fontFamily: fonts.regular, fontSize: 12.5, color: c.muted },
});
