import { useColorScheme } from 'react-native';

// The website's palette: sand, maroon, gold and teal (see touchline_takes/web/static/style.css).
const light = {
  page: '#EFE4D0',
  card: '#FAF4E8',
  sandDeep: '#E2D1B3',
  line: '#DCCBAD',
  maroon: '#6E1A2A',
  ink: '#3F121B',
  muted: '#85625A',
  gold: '#D8A23B',
  goldText: '#A3680F',
  teal: '#1F5A63',
  onDark: '#F5EAD6',
};

const dark: typeof light = {
  page: '#1C1311',
  card: '#251A17',
  sandDeep: '#2A1D19',
  line: '#3A2A24',
  maroon: '#E08A95',
  ink: '#F2E4CC',
  muted: '#B59A8A',
  gold: '#E0B158',
  goldText: '#E0B158',
  teal: '#5FA3AD',
  onDark: '#1C1311',
};

export type Colors = typeof light;

export function useColors(): Colors {
  return useColorScheme() === 'dark' ? dark : light;
}

export const fonts = {
  regular: 'DMSans-Regular',
  bold: 'DMSans-Bold',
  heavy: 'DMSans-ExtraBold',
  script: 'Yellowtail',
};
