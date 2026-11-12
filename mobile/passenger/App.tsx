// Speedo Live — passenger Android app (Expo / React Native).
import React, { useEffect, useState } from "react";
import { Platform, Text, View } from "react-native";
import { StatusBar } from "expo-status-bar";
import { NavigationContainer } from "@react-navigation/native";
import { createBottomTabNavigator } from "@react-navigation/bottom-tabs";
import { createNativeStackNavigator } from "@react-navigation/native-stack";
import { SafeAreaProvider, SafeAreaView } from "react-native-safe-area-context";
import * as Notifications from "expo-notifications";
import * as Device from "expo-device";
import { auth, post } from "./src/api";
import { C } from "./src/ui";
import { BusScreen, DemoBanner, ExploreScreen, FavoritesScreen, HomeScreen, LiveMapScreen, PlanScreen, ProfileScreen, RouteScreen, StopScreen,
  TimetableScreen } from "./src/screens";

Notifications.setNotificationHandler({
  handleNotification: async () => ({ shouldShowBanner: true, shouldShowList: true, shouldPlaySound: true, shouldSetBadge: false } as any),
});

/** Register this phone's FCM token with the backend (requires google-services.json in the build). */
async function registerPush() {
  if (!Device.isDevice || !auth.token) return;
  if (Platform.OS === "android") {
    await Notifications.setNotificationChannelAsync("bus-alerts", { name: "Bus alerts", importance: Notifications.AndroidImportance.HIGH, lightColor: C.orange });
  }
  const perm = await Notifications.requestPermissionsAsync();
  if (!perm.granted) return;
  const { data } = await Notifications.getDevicePushTokenAsync(); // native FCM token on Android
  await post("/api/me/devices", { token: String(data), platform: "android" });
}

const Tab = createBottomTabNavigator();
const Stack = createNativeStackNavigator();
const icon = (glyph: string) => ({ color }: { color: string }) => <Text style={{ fontSize: 20, color }}>{glyph}</Text>;

function Tabs() {
  return (
    <Tab.Navigator screenOptions={{ tabBarActiveTintColor: C.blue, tabBarInactiveTintColor: "#6B7890", headerStyle: { backgroundColor: C.blue }, headerTintColor: "#fff" }}>
      <Tab.Screen name="Home" component={HomeScreen} options={{ tabBarIcon: icon("⌂"), title: "Speedo Live" , tabBarLabel: "Home" }} />
      <Tab.Screen name="Explore" component={ExploreScreen} options={{ tabBarIcon: icon("⤳") }} />
      <Tab.Screen name="Live Map" component={LiveMapScreen} options={{ tabBarIcon: icon("🚌") }} />
      <Tab.Screen name="Favorites" component={FavoritesScreen} options={{ tabBarIcon: icon("★") }} />
      <Tab.Screen name="Profile" options={{ tabBarIcon: icon("◉") }}>{() => <ProfileScreen registerPush={registerPush} />}</Tab.Screen>
    </Tab.Navigator>
  );
}

export default function App() {
  const [ready, setReady] = useState(false);
  useEffect(() => { auth.load().finally(() => setReady(true)); }, []);
  if (!ready) return <View style={{ flex: 1, backgroundColor: C.blue }} />;
  return (
    <SafeAreaProvider>
      <StatusBar style="light" />
      <SafeAreaView style={{ flex: 1, backgroundColor: C.blue }} edges={["top"]}>
        <DemoBanner />
        <NavigationContainer>
          <Stack.Navigator screenOptions={{ headerStyle: { backgroundColor: C.blue }, headerTintColor: "#fff" }}>
            <Stack.Screen name="Tabs" component={Tabs} options={{ headerShown: false }} />
            <Stack.Screen name="Route" component={RouteScreen} options={({ route }: any) => ({ title: route.params?.name || "Route" })} />
            <Stack.Screen name="Stop" component={StopScreen} options={({ route }: any) => ({ title: route.params?.name || "Stop" })} />
            <Stack.Screen name="Bus" component={BusScreen} options={{ title: "Bus" }} />
            <Stack.Screen name="Plan" component={PlanScreen} options={{ title: "Journey options" }} />
            <Stack.Screen name="Timetable" component={TimetableScreen} />
          </Stack.Navigator>
        </NavigationContainer>
      </SafeAreaView>
    </SafeAreaProvider>
  );
}
