import { useEffect, useState } from "react";
import { Text } from "react-native";
import { NavigationContainer } from "@react-navigation/native";
import { createBottomTabNavigator } from "@react-navigation/bottom-tabs";
import { createNativeStackNavigator } from "@react-navigation/native-stack";
import { SafeAreaProvider, SafeAreaView } from "react-native-safe-area-context";
import { StatusBar } from "expo-status-bar";
import { DemoBanner } from "./src/components/ui";
import { api } from "./src/lib/api";
import { AuthProvider } from "./src/lib/hooks";
import { registerForPush } from "./src/lib/push";
import { C } from "./src/lib/theme";
import HomeScreen from "./src/screens/HomeScreen";
import ExploreScreen from "./src/screens/ExploreScreen";
import LiveMapScreen from "./src/screens/LiveMapScreen";
import StopScreen from "./src/screens/StopScreen";
import { FavoritesScreen, ProfileScreen, RouteScreen, TimetableScreen } from "./src/screens/OtherScreens";

export type RootStack = {
  Tabs: undefined;
  Stop: { id: number; routeId?: number; tracking?: boolean };
  Route: { id: number };
  Timetable: { routeId?: number };
};

const Stack = createNativeStackNavigator<RootStack>();
const Tab = createBottomTabNavigator();

const ICONS: Record<string, string> = { Home: "⌂", Explore: "⇄", LiveMap: "◉", Favorites: "★", Profile: "☺" };

function Tabs() {
  return (
    <Tab.Navigator
      screenOptions={({ route }) => ({
        headerStyle: { backgroundColor: C.brand },
        headerTintColor: "#fff",
        headerTitleStyle: { fontWeight: "800" },
        tabBarActiveTintColor: C.brand,
        tabBarInactiveTintColor: "#94a3b8",
        tabBarIcon: ({ color }) => <Text style={{ color, fontSize: 20 }}>{ICONS[route.name]}</Text>,
      })}
    >
      <Tab.Screen name="Home" component={HomeScreen as never} options={{ title: "Speedo Live" }} />
      <Tab.Screen name="Explore" component={ExploreScreen} options={{ title: "Explore routes", tabBarLabel: "Explore" }} />
      <Tab.Screen name="LiveMap" component={LiveMapScreen} options={{ title: "Live Map", tabBarLabel: "Live Map" }} />
      <Tab.Screen name="Favorites" component={FavoritesScreen} />
      <Tab.Screen name="Profile" component={ProfileScreen} />
    </Tab.Navigator>
  );
}

export default function App() {
  const [demo, setDemo] = useState(false);
  useEffect(() => {
    api<{ demo_mode: boolean }>("/api/meta").then((m) => setDemo(m.demo_mode)).catch(() => {});
  }, []);
  return (
    <SafeAreaProvider>
      <AuthProvider onSignedIn={() => registerForPush()}>
        <SafeAreaView edges={["top"]} style={{ flex: 0, backgroundColor: demo ? C.accent : C.brand }} />
        <StatusBar style="light" />
        <DemoBanner show={demo} />
        {/* nested provider measures insets from below the banner, so headers do not add the status bar again */}
        <SafeAreaProvider style={{ flex: 1 }}>
          <NavigationContainer>
            <Stack.Navigator screenOptions={{ headerStyle: { backgroundColor: C.brand }, headerTintColor: "#fff" }}>
              <Stack.Screen name="Tabs" component={Tabs} options={{ headerShown: false }} />
              <Stack.Screen name="Stop" component={StopScreen} options={{ title: "Bus stop" }} />
              <Stack.Screen name="Route" component={RouteScreen} options={{ title: "Route" }} />
              <Stack.Screen name="Timetable" component={TimetableScreen} />
            </Stack.Navigator>
          </NavigationContainer>
        </SafeAreaProvider>
      </AuthProvider>
    </SafeAreaProvider>
  );
}
