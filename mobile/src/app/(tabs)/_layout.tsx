import Ionicons from '@expo/vector-icons/Ionicons';
import { Tabs } from 'expo-router';

import { useStore } from '../../lib/store';
import { fonts, useColors } from '../../lib/theme';

export default function TabsLayout() {
  const c = useColors();
  const { newForMe } = useStore();
  return (
    <Tabs
      screenOptions={{
        headerShown: false,
        tabBarActiveTintColor: c.maroon,
        tabBarInactiveTintColor: c.muted,
        tabBarStyle: { backgroundColor: c.card, borderTopColor: c.line },
        tabBarLabelStyle: { fontFamily: fonts.bold, fontSize: 11 },
      }}>
      <Tabs.Screen
        name="index"
        options={{
          title: 'Latest',
          tabBarIcon: ({ color, size }) => <Ionicons name="newspaper-outline" color={color as string} size={size} />,
        }}
      />
      <Tabs.Screen
        name="mine"
        options={{
          title: 'My clubs',
          tabBarBadge: newForMe > 0 ? newForMe : undefined,
          tabBarBadgeStyle: { backgroundColor: c.gold, color: '#2B1A10', fontFamily: fonts.bold },
          tabBarIcon: ({ color, size }) => <Ionicons name="star-outline" color={color as string} size={size} />,
        }}
      />
      <Tabs.Screen
        name="clubs"
        options={{
          title: 'Clubs',
          tabBarIcon: ({ color, size }) => <Ionicons name="shield-outline" color={color as string} size={size} />,
        }}
      />
    </Tabs>
  );
}
