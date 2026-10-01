import { Ionicons } from '@expo/vector-icons';
import { useRouter, useFocusEffect } from 'expo-router';
import React, { useCallback, useEffect, useState } from 'react';
// Sửa dòng 4 thành:
import { ActivityIndicator, Alert, FlatList, Image, StyleSheet, Text, TouchableOpacity, View, Linking } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { api } from '../service/api';
import { supabase } from '../../supabase';
import { useUserPreference } from '../store/userPreference';

const LOCAL_MOVIE_ID_MAX = 2000;

export default function ProfileScreen() {
    const router = useRouter();
    const { sessionId, resetSession } = useUserPreference();
    const [profileName, setProfileName] = useState<string | null>(null);
    const [profileRole, setProfileRole] = useState<string | null>(null);
    const [profileEmail, setProfileEmail] = useState<string | null>(null);
    const [vipUser, setVipUser] = useState<boolean>(false);
    const [vipExpiredAt, setVipExpiredAt] = useState<string | null>(null);
    const [ratedMovies, setRatedMovies] = useState<any[]>([]);
    const [watchHistory, setWatchHistory] = useState<any[]>([]);
    const [loading, setLoading] = useState(true);
    const [activeTab, setActiveTab] = useState<'rated' | 'watched'>('rated');
    const [ratingCount, setRatingCount] = useState<number>(0);

    const loadRatings = async () => {
        try {
            // Ensure Supabase auth session is ready before calling
            const waitForSession = async (tries = 6, delayMs = 250) => {
                for (let i = 0; i < tries; i++) {
                    const { data } = await supabase.auth.getSession();
                    if (data?.session) return true;
                    await new Promise((r) => setTimeout(r, delayMs));
                }
                return false;
            };

            await waitForSession();
            const data = await api.getUserRatings(sessionId);
            console.debug('[PROFILE] getUserRatings response:', data);
            const mergedRatings: Record<string, number> = {};
            (data.ratings || []).forEach((item: any) => {
                mergedRatings[item.movie_id.toString()] = Number(item.rating);
            });

            // authoritative count from Supabase
            setRatingCount((data.ratings || []).length);

            const enrichedRatings = await Promise.all(
                Object.entries(mergedRatings).map(async ([movieIdString, rating]) => {
                    const movieId = parseInt(movieIdString, 10);
                    let movieData: any = null;
                    let usedTmdb = movieId > LOCAL_MOVIE_ID_MAX;

                    try {
                        if (usedTmdb) {
                            movieData = await api.getTmdbMovieDetails(movieId);
                        } else {
                            movieData = await api.getMovieDetails(movieId);
                            if (!movieData || movieData.error || !movieData.title) {
                                usedTmdb = true;
                                movieData = await api.getTmdbMovieDetails(movieId);
                            }
                        }
                    } catch (error) {
                        console.error('Failed to fetch movie details for rating:', movieIdString, error);
                        movieData = null;
                    }

                    const rawPoster = movieData?.poster_path || movieData?.tmdb?.poster_path;
                    const posterPath = rawPoster
                        ? (rawPoster.startsWith('http') ? rawPoster : `https://image.tmdb.org/t/p/w342${rawPoster}`)
                        : 'https://via.placeholder.com/150x225?text=No+Poster';

                    return {
                        movie_id: movieIdString,
                        rating,
                        title: movieData?.title || `Phim #${movieIdString}`,
                        poster_path: posterPath,
                        genres: movieData?.genres || movieData?.tmdb?.genres || [],
                        isTmdb: usedTmdb,
                    };
                })
            );
            setRatedMovies(enrichedRatings);
        } catch (error) {
            console.error('Failed to load user ratings:', error);
        }
    };

const loadProfile = async () => {
    try {
        const { data: sessionData } = await supabase.auth.getSession();
        const userId = sessionData?.session?.user?.id;
        if (!userId) return;

        // Chọn thêm các cột 'role', 'vip_user', 'vip_expired_at' từ bảng profile
        const { data, error } = await supabase
            .from('profile')
            .select('name, email, role, vip_user, vip_expired_at')
            .eq('id', userId)
            .single();
            
        if (error) {
            console.error('Failed to load profile:', error);
            return;
        }
        setProfileName(data?.name || null);
        setProfileEmail(data?.email || null);
        setProfileRole(data?.role || null);
        setVipUser(data?.vip_user || false);
        setVipExpiredAt(data?.vip_expired_at || null);
    } catch (e) {
        console.error('Error fetching profile:', e);
    }
};


    const loadWatchHistory = async () => {
        try {
            const data = await api.getWatchHistory();
            const enrichedHistory = await Promise.all(
                (data.watch_history || []).map(async (item: any) => {
                    const movieId = parseInt(item.movie_id, 10);
                    let movieData: any = null;
                    let usedTmdb = movieId > LOCAL_MOVIE_ID_MAX;

                    try {
                        if (usedTmdb) {
                            movieData = await api.getTmdbMovieDetails(movieId);
                        } else {
                            movieData = await api.getMovieDetails(movieId);
                            if (!movieData || movieData.error || !movieData.title) {
                                usedTmdb = true;
                                movieData = await api.getTmdbMovieDetails(movieId);
                            }
                        }
                    } catch (error) {
                        console.error('Failed to fetch movie details for watch history:', item.movie_id, error);
                        movieData = null;
                    }

                    const rawPoster = movieData?.poster_path || movieData?.tmdb?.poster_path;
                    const posterPath = rawPoster
                        ? (rawPoster.startsWith('http') ? rawPoster : `https://image.tmdb.org/t/p/w342${rawPoster}`)
                        : 'https://via.placeholder.com/150x225?text=No+Poster';

                    return {
                        ...item,
                        title: movieData?.title || `Phim #${item.movie_id}`,
                        poster_path: posterPath,
                        genres: movieData?.genres || movieData?.tmdb?.genres || [],
                        isTmdb: usedTmdb,
                    };
                })
            );
            setWatchHistory(enrichedHistory);
        } catch (error) {
            console.error('Failed to load watch history:', error);
        }
    };

    const loadAllData = async () => {
        setLoading(true);
        try {
            await Promise.all([loadRatings(), loadWatchHistory()]);
        } finally {
            setLoading(false);
        }
    };

        useEffect(() => {
        // Hàm xử lý khi bắt được Deep Link trả về kết quả thanh toán
        const handleDeepLink = (event: { url: string }) => {
            const url = event.url;
            console.debug('[PROFILE] Nhận Deep Link:', url);
            
            if (url.includes('payment-result')) {
                if (url.includes('status=success')) {
                    Alert.alert(
                        'Thành công 🎉',
                        'Tài khoản của bạn đã được nâng cấp lên VIP Premium!',
                        [
                            {
                                text: 'Xem phim ngay 🎬',
                                onPress: () => {
                                    router.replace('/' as any); // Chuyển hướng về Trang chủ
                                }
                            }
                        ]
                    );
                    loadProfile(); // Tải lại profile để cập nhật huy hiệu VIP màu vàng
                } else {
                    Alert.alert('Thất bại ❌', 'Giao dịch thanh toán không thành công hoặc đã bị hủy.');
                }
            }
        };

        // Đăng ký bộ lắng nghe sự kiện Deep Link
        const subscription = Linking.addEventListener('url', handleDeepLink);

        // Trường hợp app đang bị tắt hoàn toàn và được mở lên thông qua Deep Link
        Linking.getInitialURL().then((url) => {
            if (url) handleDeepLink({ url });
        });

        return () => {
            subscription.remove(); // Hủy đăng ký khi thoát màn hình
        };
    }, []);


    useFocusEffect(
        useCallback(() => {
            loadAllData();
            loadProfile();
        }, [sessionId])
    );

    const handleReset = () => {
        Alert.alert(
            'Xóa dữ liệu & Reset',
            'Thao tác này sẽ xóa đánh giá và lịch sử xem của bạn, sau đó tạo một phiên mới. Bạn có muốn tiếp tục không?',
            [
                { text: 'Hủy', style: 'cancel' },
                {
                    text: 'Xóa',
                    style: 'destructive',
                    onPress: async () => {
                        try {
                            setLoading(true);
                            await api.resetUserData(sessionId);
                            resetSession();
                            router.replace('/onboarding' as any);
                        } catch (error) {
                            console.error('Failed to reset user data:', error);
                            Alert.alert('Lỗi', 'Không thể xóa dữ liệu lúc này. Vui lòng thử lại.');
                        } finally {
                            setLoading(false);
                        }
                    }
                }
            ]
        );
    };

    const handleLogout = async () => {
        Alert.alert(
            'Đăng xuất',
            'Bạn có chắc muốn đăng xuất?',
            [
                { text: 'Hủy', style: 'cancel' },
                {
                    text: 'Đăng xuất',
                    onPress: async () => {
                        await supabase.auth.signOut();
                        router.replace('/log-in' as any);
                    }
                }
            ]
        );
    };

        const handleUpgradePremium = async (amount: number, packageType: string) => {
        try {
            setLoading(true);
            // 1. Tạo mã đơn hàng duy nhất bằng cách ghép chuỗi thời gian
            const orderId = `VIP_${Date.now()}`;

            // 2. Gọi Edge Function qua helper API
            const response = await api.createVnpayPayment(amount, orderId, packageType);

            if (response && response.status === 'success' && response.payment_url) {
                // 3. Mở URL thanh toán VNPay bằng trình duyệt mặc định của điện thoại
                Linking.openURL(response.payment_url);
            } else {
                Alert.alert('Lỗi', response?.message || 'Không thể tạo link thanh toán vào lúc này.');
            }
        } catch (error: any) {
            console.error('Lỗi nâng cấp Premium:', error);
            Alert.alert('Lỗi', error.message || 'Đã xảy ra lỗi kết nối thanh toán.');
        } finally {
            setLoading(false);
        }
    };


    const renderGenres = (item: any) => {
        const genres = item.genres || (item.tmdb?.genres ? item.tmdb.genres.map((g: any) => typeof g === 'string' ? g : g.name) : []);
        return genres.length > 0 ? genres.slice(0, 3).join(' • ') : 'Không rõ thể loại';
    };

    const formatWatchDate = (dateString: string) => {
        const date = new Date(dateString);
        const now = new Date();
        const diffMs = now.getTime() - date.getTime();
        const diffMins = Math.floor(diffMs / 60000);
        const diffHours = Math.floor(diffMs / 3600000);
        const diffDays = Math.floor(diffMs / 86400000);

        if (diffMins < 1) return 'Vừa xem';
        if (diffMins < 60) return `${diffMins}m trước`;
        if (diffHours < 24) return `${diffHours}h trước`;
        if (diffDays < 7) return `${diffDays}d trước`;
        
        return date.toLocaleDateString('vi-VN');
    };

    const handleOpenMovie = (item: any) => {
        const movieId = item.movie_id || item.id;
        const isTmdb = item.isTmdb || Number(movieId) > LOCAL_MOVIE_ID_MAX;
        router.push(`/movie/${movieId}?isTmdb=${isTmdb}`);
    };

    const currentData = activeTab === 'rated' ? ratedMovies : watchHistory;
    const currentTitle = activeTab === 'rated' 
        ? `Phim đã đánh giá (${ratingCount})`
        : `Lịch sử xem (${watchHistory.length})`;

    return (
        <SafeAreaView style={styles.container}>
            <View style={styles.header}>
                <View style={styles.avatarContainer}>
                    <Text style={styles.avatarText}>{profileName ? profileName.charAt(0).toUpperCase() : 'U'}</Text>
                </View>
                <Text style={styles.username}>{profileName || profileEmail || 'Người dùng ẩn danh'}</Text>
                {profileEmail ? <Text style={styles.emailText}>{profileEmail}</Text> : null}
{vipUser && vipExpiredAt ? (
    <View style={styles.premiumBadge}>
        <Ionicons name="star" size={14} color="#FFD700" style={{ marginRight: 4 }} />
        <Text style={styles.premiumText}>
            VIP PREMIUM (Hạn: {new Date(vipExpiredAt).toLocaleDateString('vi-VN')})
        </Text>
    </View>
) : null}

                <Text style={styles.sessionId}>ID: {sessionId.substring(0, 8)}...</Text>
    <View style={styles.upgradeSection}>
        <Text style={styles.upgradeTitle}>
            {vipUser ? "Gia hạn thêm gói VIP 🌟" : "Nâng cấp tài khoản VIP"}
        </Text>
        <View style={styles.packagesContainer}>
            <TouchableOpacity 
                style={styles.packageCard} 
                onPress={() => handleUpgradePremium(50000, '1_month')}
            >
                <Text style={styles.packageDuration}>1 Tháng</Text>
                <Text style={styles.packagePrice}>50k</Text>
            </TouchableOpacity>
            
            <TouchableOpacity 
                style={[styles.packageCard, styles.popularPackage]} 
                onPress={() => handleUpgradePremium(250000, '6_months')}
            >
                <View style={styles.hotBadge}>
                    <Text style={styles.hotText}>HOT</Text>
                </View>
                <Text style={[styles.packageDuration, { color: '#FFF' }]}>6 Tháng</Text>
                <Text style={[styles.packagePrice, { color: '#FFD700' }]}>250k</Text>
            </TouchableOpacity>
            
            <TouchableOpacity 
                style={styles.packageCard} 
                onPress={() => handleUpgradePremium(450000, '1_year')}
            >
                <Text style={styles.packageDuration}>1 Năm</Text>
                <Text style={styles.packagePrice}>450k</Text>
            </TouchableOpacity>
        </View>
    </View>
                <TouchableOpacity style={styles.resetButton} onPress={handleReset}>
                    <Text style={styles.resetText}>Xóa dữ liệu & Reset</Text>
                </TouchableOpacity>
                <TouchableOpacity style={styles.logoutButton} onPress={handleLogout}>
                    <Text style={styles.logoutText}>Đăng xuất</Text>
                </TouchableOpacity>
            </View>

            {/* Tab Navigation */}
            <View style={styles.tabContainer}>
                <TouchableOpacity 
                    style={[styles.tabButton, activeTab === 'rated' && styles.activeTab]}
                    onPress={() => setActiveTab('rated')}
                >
                    <Ionicons name="star" size={18} color={activeTab === 'rated' ? '#007AFF' : '#666'} />
                    <Text style={[styles.tabText, activeTab === 'rated' && styles.activeTabText]}>
                        Đánh giá
                    </Text>
                </TouchableOpacity>
                <TouchableOpacity 
                    style={[styles.tabButton, activeTab === 'watched' && styles.activeTab]}
                    onPress={() => setActiveTab('watched')}
                >
                    <Ionicons name="play-circle" size={18} color={activeTab === 'watched' ? '#007AFF' : '#666'} />
                    <Text style={[styles.tabText, activeTab === 'watched' && styles.activeTabText]}>
                        Xem gần đây
                    </Text>
                </TouchableOpacity>
            </View>

            <View style={styles.content}>
                <View style={styles.sectionHeader}>
                    <Text style={styles.sectionTitle}>{currentTitle}</Text>
                    <TouchableOpacity onPress={loadAllData}>
                        <Ionicons name="refresh" size={20} color="#007AFF" />
                    </TouchableOpacity>
                </View>

                {loading ? (
                    <ActivityIndicator size="large" color="#007AFF" style={{ marginTop: 40 }} />
                ) : (
                    <FlatList
                        data={currentData}
                        keyExtractor={(item) => String(item.movie_id)}
                        renderItem={({ item }) => (
                            <TouchableOpacity style={styles.ratingItem} onPress={() => handleOpenMovie(item)}>
                                <Image
                                    source={{ uri: item.poster_path || 'https://via.placeholder.com/150x225?text=No+Poster' }}
                                    style={styles.poster}
                                />
                                <View style={styles.movieInfo}>
                                    <Text style={styles.movieTitle}>{item.title || `Phim #${item.movie_id}`}</Text>
                                    <Text style={styles.genresText}>{renderGenres(item)}</Text>
                                    {activeTab === 'rated' && item.rating && (
                                        <View style={styles.stars}>
                                            {[1, 2, 3, 4, 5].map((s) => (
                                                <Ionicons
                                                    key={s}
                                                    name={item.rating >= s ? 'star' : 'star-outline'}
                                                    size={16}
                                                    color="#FFD700"
                                                />
                                            ))}
                                        </View>
                                    )}
                                    {activeTab === 'watched' && item.watched_at && (
                                        <Text style={styles.watchDateText}>{formatWatchDate(item.watched_at)}</Text>
                                    )}
                                </View>
                                {activeTab === 'rated' && (
                                    <Text style={styles.ratingValue}>{item.rating}/5</Text>
                                )}
                            </TouchableOpacity>
                        )}
                        ItemSeparatorComponent={() => <View style={styles.separator} />}
                        contentContainerStyle={styles.listContent}
                        ListEmptyComponent={
                            <View style={styles.emptyContainer}>
                                <Text style={styles.emptyText}>
                                    {activeTab === 'rated' 
                                        ? 'Bạn chưa đánh giá phim nào.'
                                        : 'Bạn chưa xem phim nào.'}
                                </Text>
                            </View>
                        }
                    />
                )}
            </View>
        </SafeAreaView>
    );
}

const styles = StyleSheet.create({
    container: {
        flex: 1,
        backgroundColor: '#121212',
    },
    header: {
        alignItems: 'center',
        padding: 30,
        backgroundColor: '#1a1a1a',
        borderBottomWidth: 1,
        borderBottomColor: '#222',
    },
    avatarContainer: {
        width: 80,
        height: 80,
        borderRadius: 40,
        backgroundColor: '#007AFF',
        justifyContent: 'center',
        alignItems: 'center',
        marginBottom: 15,
    },
    avatarText: {
        color: '#fff',
        fontSize: 32,
        fontWeight: 'bold',
    },
    username: {
        fontSize: 22,
        fontWeight: 'bold',
        color: '#fff',
    },
    emailText: {
        fontSize: 14,
        color: '#aaa',
        marginTop: 4,
    },
    sessionId: {
        fontSize: 14,
        color: '#aaa',
        marginTop: 4,
    },
    tabContainer: {
        flexDirection: 'row',
        borderBottomWidth: 1,
        borderBottomColor: '#222',
        backgroundColor: '#121212',
        paddingHorizontal: 20,
    },
    tabButton: {
        flex: 1,
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'center',
        paddingVertical: 12,
        borderBottomWidth: 2,
        borderBottomColor: 'transparent',
    },
    activeTab: {
        borderBottomColor: '#007AFF',
    },
    tabText: {
        marginLeft: 8,
        fontSize: 14,
        color: '#aaa',
        fontWeight: '500',
    },
    activeTabText: {
        color: '#007AFF',
        fontWeight: '600',
    },
    resetButton: {
        marginTop: 20,
        paddingHorizontal: 15,
        paddingVertical: 8,
        borderRadius: 15,
        borderWidth: 1,
        borderColor: '#ff4d4d',
    },
    resetText: {
        color: '#ff4d4d',
        fontWeight: '600',
    },
    logoutButton: {
        marginTop: 10,
        paddingHorizontal: 15,
        paddingVertical: 8,
        borderRadius: 15,
        borderWidth: 1,
        borderColor: '#007AFF',
    },
    logoutText: {
        color: '#007AFF',
        fontWeight: '600',
    },
    content: {
        flex: 1,
    },
    sectionHeader: {
        flexDirection: 'row',
        justifyContent: 'space-between',
        alignItems: 'center',
        padding: 20,
        backgroundColor: '#121212',
    },
    sectionTitle: {
        fontSize: 18,
        fontWeight: 'bold',
        color: '#fff',
    },
    listContent: {
        paddingHorizontal: 20,
    },
    ratingItem: {
        flexDirection: 'row',
        alignItems: 'center',
        paddingVertical: 15,
    },
    poster: {
        width: 80,
        height: 120,
        borderRadius: 10,
        marginRight: 12,
        backgroundColor: '#f0f0f0',
    },
    movieInfo: {
        flex: 1,
    },
    movieTitle: {
        fontSize: 16,
        fontWeight: '600',
        color: '#fff',
        marginBottom: 6,
    },
    genresText: {
        fontSize: 13,
        color: '#aaa',
        marginBottom: 8,
    },
    watchDateText: {
        fontSize: 12,
        color: '#999',
        marginTop: 4,
    },
    stars: {
        flexDirection: 'row',
    },
    ratingValue: {
        fontSize: 16,
        fontWeight: 'bold',
        color: '#007AFF',
        marginLeft: 12,
    },
    separator: {
        height: 1,
        backgroundColor: '#222',
    },
    emptyContainer: {
        alignItems: 'center',
        marginTop: 100,
    },
    emptyText: {
        color: '#999',
        fontSize: 16,
    },
    premiumBadge: {
        flexDirection: 'row',
        alignItems: 'center',
        backgroundColor: 'rgba(255, 215, 0, 0.15)',
        paddingHorizontal: 10,
        paddingVertical: 4,
        borderRadius: 12,
        borderWidth: 1,
        borderColor: '#FFD700',
        marginTop: 8,
    },
    premiumText: {
        color: '#FFD700',
        fontSize: 12,
        fontWeight: 'bold',
    },
    upgradeSection: {
        width: '100%',
        marginTop: 20,
        alignItems: 'center',
    },
    upgradeTitle: {
        fontSize: 16,
        fontWeight: 'bold',
        color: '#D4AF37', // Gold
        marginBottom: 12,
    },
    packagesContainer: {
        flexDirection: 'row',
        justifyContent: 'space-between',
        width: '100%',
        paddingHorizontal: 5,
    },
    packageCard: {
        flex: 1,
        backgroundColor: '#222',
        paddingVertical: 15,
        marginHorizontal: 5,
        borderRadius: 12,
        alignItems: 'center',
        borderWidth: 1,
        borderColor: '#333',
    },
    popularPackage: {
        borderColor: '#D4AF37',
        backgroundColor: '#2a220f', // slight golden tint
        position: 'relative',
    },
    packageDuration: {
        fontSize: 14,
        fontWeight: '600',
        color: '#aaa',
        marginBottom: 4,
    },
    packagePrice: {
        fontSize: 16,
        fontWeight: 'bold',
        color: '#FFF',
    },
    hotBadge: {
        position: 'absolute',
        top: -10,
        backgroundColor: '#E50914', // Red badge
        paddingHorizontal: 8,
        paddingVertical: 2,
        borderRadius: 8,
    },
    hotText: {
        color: '#FFF',
        fontSize: 10,
        fontWeight: 'bold',
    },

});
