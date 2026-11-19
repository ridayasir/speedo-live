/**
 * Push notifications through Firebase Cloud Messaging.
 * Needs google-services.json in the app folder at build time (see README). Without it the
 * app still works; alerts then show only in the in-app inbox.
 */
import Constants from "expo-constants";
import * as Device from "expo-device";
import * as Notifications from "expo-notifications";
import { Platform } from "react-native";
import { api } from "./api";

Notifications.setNotificationHandler({
  handleNotification: async () => ({ shouldShowAlert: true, shouldPlaySound: true, shouldSetBadge: false }),
});

export async function registerForPush(): Promise<string | null> {
  if (!Device.isDevice || !Constants.expoConfig?.extra?.pushEnabled) return null;
  if (Platform.OS === "android") {
    await Notifications.setNotificationChannelAsync("bus-alerts", {
      name: "Bus alerts",
      importance: Notifications.AndroidImportance.HIGH,
      vibrationPattern: [0, 250, 250, 250],
      lightColor: "#f97316",
    });
  }
  const { status: existing } = await Notifications.getPermissionsAsync();
  let status = existing;
  if (existing !== "granted") status = (await Notifications.requestPermissionsAsync()).status;
  if (status !== "granted") return null;
  try {
    const token = (await Notifications.getDevicePushTokenAsync()).data as string; // native FCM token
    await api("/api/me/devices", { method: "POST", json: { token, platform: "android" } });
    return token;
  } catch {
    return null;
  }
}
