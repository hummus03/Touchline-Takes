# Touchline Takes for iPhone (and Android)

An Expo (React Native) app for touchlinetakes.com. It reads the site's static JSON feed
(`https://touchlinetakes.com/api/v1/`, built by `touchline_takes/web/api.py`), so it needs
no server of its own.

## What it does

- **Latest:** every published take, newest first. Pull down to refresh.
- **Clubs:** every club covered, grouped by league, with search. Tap the star to follow.
- **My clubs:** takes about the clubs you follow, with a badge on the tab for takes
  published since you last looked.
- **Article:** the full take with its citation markers, the "Touchline Take" verdict, and
  the sources (opened in an in-app browser). Follow a club from the article too.
- **Offline:** the last copy of each feed and article is kept on the phone.
- Light and dark mode, in the site's sand, maroon and gold.

Followed clubs are stored only on the phone. There are no accounts, and nothing is sent to
us.

## Run it on your iPhone (free, no Apple account needed)

You need a Mac with Node.js 22 or newer (`node -v`), and the **Expo Go** app from the App
Store on your iPhone, on the same Wi-Fi as the Mac.

```bash
cd mobile
```

```bash
npm install
```

```bash
npx expo start
```

Scan the QR code it prints with the iPhone's camera, and the app opens in Expo Go. Edits
reload on the phone as you save. With Xcode installed, press `i` instead to open the iOS
simulator.

To try it against a local build of the site rather than touchlinetakes.com:

```bash
EXPO_PUBLIC_API_BASE=http://<your-mac-ip>:8000/api/v1 npx expo start
```

## Checks

```bash
npx tsc --noEmit
```

```bash
npx expo-doctor
```

## Next steps

1. **Push alerts for followed clubs.** These need a paid Apple Developer account ($99 a
   year) and a development build. The plan is Firebase Cloud Messaging topics (free): the
   phone subscribes to a topic per followed club, and the deploy job sends to that topic
   when a take about the club is published, so we never store device tokens.
2. **App Store.** Build and submit with EAS (`npx eas-cli@latest build -p ios`, then
   `submit`). The App Store listing needs screenshots, a privacy policy URL
   (https://touchlinetakes.com/privacy/) and a support URL.
