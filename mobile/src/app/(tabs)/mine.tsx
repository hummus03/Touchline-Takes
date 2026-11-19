import { Link, useFocusEffect } from 'expo-router';
import { useCallback } from 'react';
import { FlatList, Pressable, RefreshControl, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { ArticleCard, Notice, SectionTitle } from '../../components/ui';
import { useStore } from '../../lib/store';
import { fonts, useColors } from '../../lib/theme';

export default function MyClubsScreen() {
  const c = useColors();
  const { follows, myArticles, seenAt, markSeen, loading, refresh, offline } = useStore();

  // "New" badges stay while you're looking; leaving the tab marks them as seen.
  useFocusEffect(useCallback(() => () => markSeen(), [markSeen]));

  if (follows.length === 0) {
    return (
      <SafeAreaView edges={['top']} style={{ flex: 1, backgroundColor: c.page, padding: 24, justifyContent: 'center', gap: 16 }}>
        <Text style={{ fontFamily: fonts.heavy, fontSize: 26, color: c.maroon }}>
          Follow your{' '}
          <Text style={{ fontFamily: fonts.script, color: c.goldText, fontSize: 30 }}>clubs</Text>
        </Text>
        <Text style={{ fontFamily: fonts.regular, fontSize: 16, lineHeight: 23, color: c.ink }}>
          Pick the clubs you care about and their takes will collect here, with a badge when
          something new is published.
        </Text>
        <Link href="/clubs" asChild>
          <Pressable style={{ backgroundColor: c.gold, paddingVertical: 12, paddingHorizontal: 18, alignSelf: 'flex-start', borderRadius: 2 }}>
            <Text style={{ fontFamily: fonts.bold, fontSize: 16, color: '#2B1A10' }}>Choose clubs</Text>
          </Pressable>
        </Link>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView edges={['top']} style={{ flex: 1, backgroundColor: c.page }}>
      <FlatList
        data={myArticles}
        keyExtractor={(a) => a.slug}
        contentContainerStyle={{ padding: 16, paddingBottom: 32 }}
        refreshControl={<RefreshControl refreshing={loading} onRefresh={refresh} tintColor={c.maroon} />}
        ListHeaderComponent={
          <View style={{ marginBottom: 8 }}>
            <Text style={{ fontFamily: fonts.heavy, fontSize: 26, color: c.maroon, marginBottom: 6 }}>My clubs</Text>
            <Text style={{ fontFamily: fonts.regular, fontSize: 14, color: c.muted, marginBottom: 14 }}>
              {follows.join(' · ')}
            </Text>
            {offline ? <Notice text="You're offline. Showing the takes saved on this phone." /> : null}
            <SectionTitle>Latest for you</SectionTitle>
          </View>
        }
        renderItem={({ item }) => <ArticleCard article={item} isNew={!!seenAt && item.published_at > seenAt} />}
        ListEmptyComponent={
          <Text style={{ fontFamily: fonts.regular, fontSize: 15, color: c.muted }}>
            No takes about your clubs yet. They'll appear here as soon as one is published.
          </Text>
        }
      />
    </SafeAreaView>
  );
}
