// Speedo Live Driver. Set EXPO_PUBLIC_API_URL to your API.
module.exports = {
  expo: {
    name: "Speedo Live Driver",
    slug: "speedo-live-driver",
    version: "1.0.0",
    orientation: "portrait",
    userInterfaceStyle: "light",
    icon: "./assets/icon.png",
    splash: { image: "./assets/icon.png", resizeMode: "contain", backgroundColor: "#173693" },
    android: {
      package: "pk.speedolive.driver",
      versionCode: 1,
      adaptiveIcon: { foregroundImage: "./assets/icon.png", backgroundColor: "#173693" },
      permissions: [
        "ACCESS_COARSE_LOCATION",
        "ACCESS_FINE_LOCATION",
        "ACCESS_BACKGROUND_LOCATION",
        "FOREGROUND_SERVICE",
        "FOREGROUND_SERVICE_LOCATION",
        "WAKE_LOCK",
      ],
    },
    plugins: [
      [
        "expo-location",
        {
          locationAlwaysAndWhenInUsePermission:
            "Speedo Live Driver shares your bus's location with passengers only while you have a trip running.",
          isAndroidBackgroundLocationEnabled: true,
          isAndroidForegroundServiceEnabled: true,
        },
      ],
      "expo-secure-store",
    ],
    extra: { apiUrl: process.env.EXPO_PUBLIC_API_URL || "http://10.0.2.2:8000" },
  },
};
