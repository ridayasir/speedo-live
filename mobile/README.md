# Speedo Live Android apps (Expo / React Native)

Two apps that use the same backend API as the web apps:

| App | Folder | Tabs |
|---|---|---|
| **Speedo Live** (passengers) | `passenger/` | Home, Explore, Live Map, Favorites, Profile (+ route, stop, bus, journey and timetable screens) |
| **Speedo Live Driver** | `driver/` | Dashboard, My Route, GPS Status, Trip History, Profile |

> These projects were written and syntax-checked but **not built or run**: the build workspace couldn't install npm packages or run an emulator. Expect to fix small version mismatches on the first `npx expo install --fix`.

## Build an APK

Needs Node 20+, an [Expo account](https://expo.dev) and the EAS CLI (`npm i -g eas-cli`).

```bash
cd mobile/passenger                 # or mobile/driver
npm install
npx expo install --fix              # aligns all package versions with the Expo SDK
# set your backend URL in eas.json (EXPO_PUBLIC_API_URL) or export it
eas login
eas build -p android --profile preview      # → downloadable .apk
eas build -p android --profile production   # → .aab for Google Play
```

Run on a phone during development: `npx expo run:android` (USB debugging) or a development build. The background-location and push features don't work in Expo Go; use a development build.

The default API URL `http://10.0.2.2:8000` reaches a backend on your computer from the Android emulator.

## Keys and services

- **Google Maps SDK key** (both apps): `react-native-maps` on Android needs one even though the tiles come from OpenStreetMap. Set `GOOGLE_MAPS_ANDROID_API_KEY` before building.
- **Firebase (passenger app push)**: create a Firebase project, add an Android app with package `pk.speedolive.app`, download `google-services.json`, set `GOOGLE_SERVICES_JSON=./google-services.json`. On the server, set `FCM_PROJECT_ID` and `FCM_SERVICE_ACCOUNT_FILE`. The app registers its FCM token after sign-in.

## Driver app: how location sharing works

- The driver must accept the location-sharing consent screen; it's recorded on the server.
- **Start trip** asks for location permission (“Allow all the time”), then starts an Android **foreground service** with a persistent notification. Locations are collected every `GPS_INTERVAL_SECONDS` (5 s by default) even when the screen is off.
- Each fix is first saved on the phone, then sent in batches to `/api/driver/location/batch`. With no internet the queue grows and is sent automatically later; the server ignores duplicates and keeps the newest fix as the live position.
- The server only accepts locations for the bus assigned to that driver, during an active trip. If the trip is ended by an admin or the bus is reassigned, the app stops tracking.
- **End trip**, sign-out or withdrawing consent stops the foreground service.
- If the phone restarts during a trip, opening the app resumes sharing for the still-active trip.
- Ask drivers to turn off battery optimisation for the app on phones that kill background services (some Xiaomi, Oppo, Vivo, Huawei models).
