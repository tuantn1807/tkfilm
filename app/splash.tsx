import { LinearGradient } from 'expo-linear-gradient';
import { useRouter } from 'expo-router';
import React, { useEffect } from 'react';
import { ActivityIndicator, StyleSheet, Text, View } from 'react-native';
import { supabase } from '../supabase';

const withTimeout = async <T,>(promise: Promise<T>, ms: number, fallback: T): Promise<T> => {
    return Promise.race([
        promise,
        new Promise<T>((resolve) => setTimeout(() => resolve(fallback), ms)),
    ]);
};

export default function SplashScreen() {
    const router = useRouter();

    useEffect(() => {
        const checkStatus = async () => {
            try {
                console.log('[Splash] checking auth session...');
                const sessionResult = await withTimeout(
                    supabase.auth.getSession(),
                    5000,
                    { data: { session: null }, error: null }
                );

                const session = sessionResult?.data?.session ?? null;
                console.log('[Splash] session found:', !!session);

                if (!session) {
                    console.log('[Splash] no session -> login');
                    router.replace('/log-in' as any);
                    return;
                }

                await new Promise((resolve) => setTimeout(resolve, 1000));

                const profileResult = await withTimeout(
                    supabase
                        .from('profile')
                        .select('is_locked')
                        .eq('id', session.user.id)
                        .single(),
                    5000,
                    { data: null, error: { message: 'profile fetch timeout' } }
                );

                if (profileResult.error) {
                    console.error('Không thể lấy trạng thái profile:', profileResult.error);
                    router.replace('/(tabs)');
                    return;
                }

                const profile = profileResult.data as { is_locked?: boolean } | null;
                if (profile?.is_locked === false) {
                    router.replace('/onboarding');
                } else {
                    router.replace('/(tabs)');
                }
            } catch (error) {
                console.error('Splash check failed:', error);
                router.replace('/log-in' as any);
            }
        };

        checkStatus();
    }, []);

    return (
        <LinearGradient
            colors={['#0a0505', '#1a0505', '#000000']}
            style={styles.container}
        >
            <View style={styles.logoContainer}>
                <View style={styles.iconCircle}>
                    <Text style={styles.logoIcon}>🎬</Text>
                </View>
                <Text style={styles.title}>TK FILM</Text>
                <Text style={styles.subtitle}>Gợi ý phim thông minh</Text>
            </View>

            <View style={styles.loaderContainer}>
                <ActivityIndicator size="large" color="#fff" />
                <Text style={styles.loadingText}>Đang kiểm tra trạng thái...</Text>
            </View>
        </LinearGradient>
    );
}

const styles = StyleSheet.create({
    container: {
        flex: 1,
        justifyContent: 'center',
        alignItems: 'center',
    },
    logoContainer: {
        alignItems: 'center',
        marginBottom: 80,
    },
    iconCircle: {
        width: 100,
        height: 100,
        borderRadius: 50,
        backgroundColor: 'rgba(255, 255, 255, 0.2)',
        justifyContent: 'center',
        alignItems: 'center',
        marginBottom: 20,
        borderWidth: 2,
        borderColor: 'rgba(255, 255, 255, 0.4)',
    },
    logoIcon: {
        fontSize: 50,
    },
    title: {
        fontSize: 42,
        fontWeight: 'bold',
        color: '#fff',
        letterSpacing: 2,
    },
    subtitle: {
        fontSize: 16,
        color: 'rgba(255, 255, 255, 0.8)',
        marginTop: 5,
        fontWeight: '500',
    },
    loaderContainer: {
        position: 'absolute',
        bottom: 100,
        alignItems: 'center',
    },
    loadingText: {
        color: '#fff',
        marginTop: 15,
        fontSize: 14,
        opacity: 0.8,
    }
});
