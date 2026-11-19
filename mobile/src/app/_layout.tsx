import { useFonts } from 'expo-font';
import { DarkTheme, DefaultTheme, SplashScreen, Stack, ThemeProvider } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { useEffect } from 'react';
import { useColorScheme } from 'react-native';

import { StoreProvider } from '../lib/store';
import { fonts, useColors } from '../lib/theme';

SplashScreen.preventAutoHideAsync();

export default function RootLayout() {
  const scheme = useColorScheme();
  const c = useColors();
  const [loaded, error] = useFonts({
    [fonts.regular]: require('../../assets/fonts/DMSans-Regular.ttf'),
    [fonts.bold]: require('../../assets/fonts/DMSans-Bold.ttf'),
    [fonts.heavy]: require('../../assets/fonts/DMSans-ExtraBold.ttf'),
    [fonts.script]: require('../../assets/fonts/Yellowtail.ttf'),
  });

  useEffect(() => {
    if (loaded || error) SplashScreen.hideAsync();
  }, [loaded, error]);

  if (!loaded && !error) return null;

  const base = scheme === 'dark' ? DarkTheme : DefaultTheme;
  const theme = {
    ...base,
    colors: { ...base.colors, primary: c.maroon, background: c.page, card: c.card, text: c.maroon, border: c.line },
  };

  return (
    <ThemeProvider value={theme}>
      <StoreProvider>
        <StatusBar style={scheme === 'dark' ? 'light' : 'dark'} />
        <Stack screenOptions={{ headerTitleStyle: { fontFamily: fonts.bold }, headerTintColor: c.maroon }}>
          <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
          <Stack.Screen name="article/[slug]" options={{ title: '', headerBackTitle: 'Back' }} />
        </Stack>
      </StoreProvider>
    </ThemeProvider>
  );
}
