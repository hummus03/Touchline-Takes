import Ionicons from '@expo/vector-icons/Ionicons';
import { useMemo, useState } from 'react';
import { Pressable, RefreshControl, SectionList, Text, TextInput, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { Notice } from '../../components/ui';
import type { Club } from '../../lib/api';
import { useStore } from '../../lib/store';
import { fonts, useColors } from '../../lib/theme';

export default function ClubsScreen() {
  const c = useColors();
  const { clubs, isFollowing, toggleFollow, loading, refresh, error } = useStore();
  const [query, setQuery] = useState('');

  const sections = useMemo(() => {
    const q = query.trim().toLowerCase();
    const groups = new Map<string, Club[]>();
    for (const club of clubs) {
      if (q && !club.name.toLowerCase().includes(q)) continue;
      const league = club.league || 'Other';
      groups.set(league, [...(groups.get(league) ?? []), club]);
    }
    // Premier League first, then the rest alphabetically.
    return [...groups.entries()]
      .sort(([a], [b]) => (a === 'Premier League' ? -1 : b === 'Premier League' ? 1 : a.localeCompare(b)))
      .map(([title, data]) => ({ title, data }));
  }, [clubs, query]);

  return (
    <SafeAreaView edges={['top']} style={{ flex: 1, backgroundColor: c.page }}>
      <SectionList
        sections={sections}
        keyExtractor={(club) => club.slug}
        contentContainerStyle={{ padding: 16, paddingBottom: 32 }}
        stickySectionHeadersEnabled={false}
        keyboardShouldPersistTaps="handled"
        refreshControl={<RefreshControl refreshing={loading} onRefresh={refresh} tintColor={c.maroon} />}
        ListHeaderComponent={
          <View style={{ gap: 12, marginBottom: 8 }}>
            <Text style={{ fontFamily: fonts.heavy, fontSize: 26, color: c.maroon }}>Clubs</Text>
            <Text style={{ fontFamily: fonts.regular, fontSize: 14, color: c.muted }}>
              Tap the star to follow a club. Your picks stay on this phone.
            </Text>
            {error ? <Notice text={error} /> : null}
            <TextInput
              value={query}
              onChangeText={setQuery}
              placeholder="Search clubs"
              placeholderTextColor={c.muted}
              autoCorrect={false}
              clearButtonMode="while-editing"
              style={{ fontFamily: fonts.regular, fontSize: 16, color: c.ink, backgroundColor: c.card,
                borderColor: c.line, borderWidth: 1, borderRadius: 2, paddingHorizontal: 12, paddingVertical: 10 }}
            />
          </View>
        }
        renderSectionHeader={({ section }) => (
          <Text style={{ fontFamily: fonts.bold, fontSize: 13, letterSpacing: 1.6, color: c.maroon, marginTop: 18, marginBottom: 6 }}>
            {section.title.toUpperCase()}
          </Text>
        )}
        renderItem={({ item }) => {
          const on = isFollowing(item.name);
          return (
            <Pressable
              onPress={() => toggleFollow(item.name)}
              accessibilityRole="switch"
              accessibilityState={{ checked: on }}
              accessibilityLabel={`Follow ${item.name}`}
              style={({ pressed }) => ({ flexDirection: 'row', alignItems: 'center', paddingVertical: 12,
                borderBottomWidth: 1, borderBottomColor: c.line, opacity: pressed ? 0.7 : 1 })}>
              <View style={{ flex: 1 }}>
                <Text style={{ fontFamily: fonts.bold, fontSize: 16, color: c.maroon }}>{item.name}</Text>
                <Text style={{ fontFamily: fonts.regular, fontSize: 12.5, color: c.muted }}>
                  {item.articles} take{item.articles === 1 ? '' : 's'}
                </Text>
              </View>
              <Ionicons name={on ? 'star' : 'star-outline'} size={24} color={on ? c.gold : c.muted} />
            </Pressable>
          );
        }}
      />
    </SafeAreaView>
  );
}
