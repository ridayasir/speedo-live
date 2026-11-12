// Expo config for the driver app. Background location runs as an Android
// foreground service with a persistent notification while a trip is active.
module.exports = {
  expo: {
    name: "Speedo Live Driver",
    slug: "speedo-live-driver",
    version: "1.0.0",
    orientation: "portrait",
    userInterfaceStyle: "light",
    primaryColor: "#0B3B8C",
    splash: { backgroundColor: "#0B3B8C" },
    android: {
      package: "pk.speedolive.driver",
      versionCode: 1,
      adaptiveIcon: { backgroundColor: "#0B3B8C" },
      permissions: [
        "ACCESS_COARSE_LOCATION", "ACCESS_FINE_LOCATION", "ACCESS_BACKGROUND_LOCATION",
        "FOREGROUND_SERVICE", "FOREGROUND_SERVICE_LOCATION", "WAKE_LOCK",
      ],
      config: { googleMaps: { apiKey: process.env.GOOGLE_MAPS_ANDROID_API_KEY || "" } },
    },
    plugins: [
      ["expo-location", {
        locationAlwaysAndWhenInUsePermission: "Speedo Live Driver shares your bus's location with passengers only while you have an active trip.",
        locationWhenInUsePermission: "Speedo Live Driver shares your bus's location with passengers only while you have an active trip.",
        isAndroidBackgroundLocationEnabled: true,
        isAndroidForegroundServiceEnabled: true,
      }],
    ],
    extra: { apiUrl: process.env.EXPO_PUBLIC_API_URL || "http://10.0.2.2:8000" },
  },
};
