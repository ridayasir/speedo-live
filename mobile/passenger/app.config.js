// Expo config. Set EXPO_PUBLIC_API_URL to your API (default: Android emulator -> host machine).
// Put Firebase's google-services.json next to this file to enable push notifications.
const fs = require("fs");
const hasFirebase = fs.existsSync("./google-services.json");

module.exports = {
  expo: {
    name: "Speedo Live",
    slug: "speedo-live",
    scheme: "speedolive",
    version: "1.0.0",
    orientation: "portrait",
    userInterfaceStyle: "light",
    icon: "./assets/icon.png",
    splash: { image: "./assets/icon.png", resizeMode: "contain", backgroundColor: "#173693" },
    android: {
      package: "pk.speedolive.passenger",
      versionCode: 1,
      adaptiveIcon: { foregroundImage: "./assets/icon.png", backgroundColor: "#173693" },
      permissions: ["ACCESS_COARSE_LOCATION", "ACCESS_FINE_LOCATION", "POST_NOTIFICATIONS"],
      ...(hasFirebase ? { googleServicesFile: "./google-services.json" } : {}),
    },
    plugins: [
      ["expo-location", { locationWhenInUsePermission: "Speedo Live uses your location to find nearby bus stops." }],
      ["expo-notifications", { color: "#f97316" }],
      "expo-secure-store",
    ],
    extra: { apiUrl: process.env.EXPO_PUBLIC_API_URL || "http://10.0.2.2:8000", pushEnabled: hasFirebase },
  },
};
