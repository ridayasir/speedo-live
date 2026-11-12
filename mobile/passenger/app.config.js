// Expo config. Set EXPO_PUBLIC_API_URL to your deployed backend (https://...).
// react-native-maps on Android needs a Google Maps SDK key: GOOGLE_MAPS_ANDROID_API_KEY.
// Push notifications need google-services.json from your Firebase project (FCM).
module.exports = {
  expo: {
    name: "Speedo Live",
    slug: "speedo-live",
    version: "1.0.0",
    orientation: "portrait",
    scheme: "speedolive",
    userInterfaceStyle: "light",
    primaryColor: "#0B3B8C",
    splash: { backgroundColor: "#0B3B8C" },
    android: {
      package: "pk.speedolive.app",
      versionCode: 1,
      adaptiveIcon: { backgroundColor: "#0B3B8C" },
      permissions: ["ACCESS_COARSE_LOCATION", "ACCESS_FINE_LOCATION", "POST_NOTIFICATIONS"],
      googleServicesFile: process.env.GOOGLE_SERVICES_JSON || undefined,
      config: { googleMaps: { apiKey: process.env.GOOGLE_MAPS_ANDROID_API_KEY || "" } },
    },
    plugins: [
      ["expo-location", { locationWhenInUsePermission: "Speedo Live uses your location to show nearby bus stops." }],
      ["expo-notifications", { color: "#F97316" }],
    ],
    extra: { apiUrl: process.env.EXPO_PUBLIC_API_URL || "http://10.0.2.2:8000" },
  },
};
