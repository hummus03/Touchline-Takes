import { FlatList, RefreshControl, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { ArticleCard, Notice, SectionTitle, Wordmark } from '../../components/ui';
import { useStore } from '../../lib/store';
import { fonts, useColors } from '../../lib/theme';

export default function LatestScreen() {
  const c = useColors();
  const { articles, loading, offline, error, refresh } = useStore();
  return (
    <SafeAreaView edges={['top']} style={{ flex: 1, backgroundColor: c.page }}>
      <FlatList
        data={articles}
        keyExtractor={(a) => a.slug}
        contentContainerStyle={{ padding: 16, paddingBottom: 32 }}
        refreshControl={<RefreshControl refreshing={loading} onRefresh={refresh} tintColor={c.maroon} />}
        ListHeaderComponent={
          <View style={{ marginBottom: 16, gap: 18 }}>
            <Wordmark />
            <Text style={{ fontFamily: fonts.heavy, fontSize: 28, lineHeight: 32, color: c.maroon }}>
              Football takes, checked{' '}
              <Text style={{ fontFamily: fonts.script, color: c.goldText, fontSize: 32 }}>line by line.</Text>
            </Text>
            {error ? <Notice text={error} /> : null}
            {offline && !error ? <Notice text="You're offline. Showing the takes saved on this phone." /> : null}
            <SectionTitle>Latest takes</SectionTitle>
          </View>
        }
        renderItem={({ item, index }) => <ArticleCard article={item} lead={index === 0} />}
        ListEmptyComponent={
          loading ? undefined : <Text style={{ fontFamily: fonts.regular, color: c.muted }}>No takes yet.</Text>
        }
      />
    </SafeAreaView>
  );
}
