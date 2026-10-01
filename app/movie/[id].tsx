import { Ionicons } from "@expo/vector-icons";
import { LinearGradient } from 'expo-linear-gradient';
import { useLocalSearchParams, useRouter } from "expo-router";
import React, { useCallback, useEffect, useState } from "react";
import {
    ActivityIndicator,
    Dimensions,
    FlatList,
    Image,
    ScrollView,
    StyleSheet,
    Text,
    TouchableOpacity,
    View,
    Linking,
    Alert,
    TextInput,
    Modal
} from "react-native";
import YoutubePlayer from "react-native-youtube-iframe";
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { MovieCard } from "../components/MovieCard";
import { api } from "../service/api";
import { useUserPreference } from "../store/userPreference";
import { Movie } from "../types/movie";
import { supabase } from "../../supabase";

// Extract YouTube video ID from a YouTube URL
const getYoutubeVideoId = (url: string): string | null => {
    if (!url) return null;
    const regExp = /^.*(youtu\.be\/|v\/|u\/\w\/|embed\/|watch\?v=|&v=)([^#&?]*).*/;
    const match = url.match(regExp);
    return (match && match[2].length === 11) ? match[2] : null;
};

const { width } = Dimensions.get('window');

export default function MovieDetailScreen() {
    const { id, isTmdb } = useLocalSearchParams<{ id: string, isTmdb?: string }>();
    const router = useRouter();
    const [movie, setMovie] = useState<Movie | null>(null);
    const [similar, setSimilar] = useState<Movie[]>([]);
    const [recommended, setRecommended] = useState<Movie[]>([]);
    const [loading, setLoading] = useState(true);
    const sessionId = useUserPreference((state) => state.sessionId);
    const [userRating, setUserRating] = useState(0);
    const [activeVideoId, setActiveVideoId] = useState<string | null>(null);
    const [movieLoadingMessage, setMovieLoadingMessage] = useState<string | null>(null);
    const insets = useSafeAreaInsets();

    // States cho bình luận
    const [comments, setComments] = useState<any[]>([]);
    const [commentsLoading, setCommentsLoading] = useState(true);
    const [newCommentText, setNewCommentText] = useState("");
    const [commentSubmitting, setCommentSubmitting] = useState(false);
    const [currentUser, setCurrentUser] = useState<{ id: string; name: string; vip_user?: boolean; vip_expired_at?: string | null } | null>(null);

    const loadData = useCallback(async () => {
        if (!id) return;
        setLoading(true);
        try {
            // Load details
            let movieData: Movie | null = null;
            if (isTmdb === 'true') {
                movieData = await api.getTmdbMovieDetails(parseInt(id));
            } else {
                movieData = await api.getMovieDetails(parseInt(id));
            }
           // movieData = await api.getTmdbMovieDetails(parseInt(id));
            setMovie(movieData);

            if (movieData) {
                // Load similar movies
                if (isTmdb === 'true' && movieData.tmdb?.recommendations?.results) {
                    setSimilar(movieData.tmdb.recommendations.results.slice(0, 10));
                } else {
                    const similarRes = await api.getSimilarMoviesItemToItem(parseInt(id));
                    setSimilar(similarRes.results || []);
                }
            }

            // Load user-based recommendations
            const recsRes = await api.getRecommendations(sessionId, 10);
            setRecommended(recsRes.recommendations || []);

        } catch (e) {
            console.error('Error loading movie details:', e);
        } finally {
            setLoading(false);
        }
    }, [id, sessionId, isTmdb]);

    const loadUserRating = useCallback(async () => {
        if (!id) return;

        try {
            const data = await api.getUserRatings(sessionId);
            const ratingItem = data.ratings?.find((item: any) => String(item.movie_id) === id);
            if (ratingItem) {
                setUserRating(Number(ratingItem.rating));
            } else {
                setUserRating(0);
            }
        } catch (e) {
            console.error('Failed to load user rating for movie:', e);
        }
    }, [id, sessionId]);

    // Tải danh sách bình luận
    const loadComments = useCallback(async () => {
        if (!id) return;
        setCommentsLoading(true);
        try {
            const res = await api.getMovieComments(parseInt(id, 10));
            setComments(res.comments || []);
        } catch (e) {
            console.error('Failed to load comments:', e);
        } finally {
            setCommentsLoading(false);
        }
    }, [id]);

    // Kiểm tra trạng thái đăng nhập của người dùng
    const checkUserAuth = useCallback(async () => {
        try {
            const { data: sessionData } = await supabase.auth.getSession();
            const userUuid = sessionData?.session?.user?.id;
            if (userUuid) {
                const { data: profile, error } = await supabase
                    .from('profile')
                    .select('name, vip_user, vip_expired_at')
                    .eq('id', userUuid)
                    .single();
                
                if (error) {
                    console.error('Failed to load user profile name:', error);
                }

                setCurrentUser({
                    id: userUuid,
                    name: profile?.name || 'Người dùng ẩn danh',
                    vip_user: profile?.vip_user || false,
                    vip_expired_at: profile?.vip_expired_at || null,
                });
            } else {
                setCurrentUser(null);
            }
        } catch (e) {
            console.error('Error checking user auth:', e);
        }
    }, []);

    // Gửi bình luận mới
    const handleAddComment = async () => {
        if (!id) return;
        if (!newCommentText.trim()) {
            Alert.alert('Thông báo', 'Vui lòng nhập nội dung bình luận.');
            return;
        }

        setCommentSubmitting(true);
        try {
            const res = await api.addMovieComment(parseInt(id, 10), newCommentText);
            if (res.success && res.comment) {
                setNewCommentText('');
                // Thêm bình luận mới vào đầu danh sách (optimistic UI update)
                setComments(prev => [res.comment, ...prev]);
            } else {
                Alert.alert('Lỗi', res.error || 'Không thể gửi bình luận.');
            }
        } catch (e) {
            console.error('Failed to add comment:', e);
            Alert.alert('Lỗi', 'Có lỗi xảy ra khi gửi bình luận.');
        } finally {
            setCommentSubmitting(false);
        }
    };

    // Xoá bình luận
    const handleDeleteComment = (commentId: string) => {
        Alert.alert(
            'Xoá bình luận',
            'Bạn có chắc chắn muốn xoá bình luận này không?',
            [
                { text: 'Hủy', style: 'cancel' },
                {
                    text: 'Xoá',
                    style: 'destructive',
                    onPress: async () => {
                        try {
                            const res = await api.deleteMovieComment(commentId);
                            if (res.success) {
                                setComments(prev => prev.filter(c => c.id !== commentId));
                            } else {
                                Alert.alert('Lỗi', res.error || 'Không thể xoá bình luận.');
                            }
                        } catch (e) {
                            console.error('Failed to delete comment:', e);
                            Alert.alert('Lỗi', 'Có lỗi xảy ra khi xoá bình luận.');
                        }
                    }
                }
            ]
        );
    };

    // Định dạng thời gian hiển thị bình luận thân thiện
    const formatCommentDate = (dateString: string) => {
        try {
            const date = new Date(dateString);
            const now = new Date();
            const diffMs = now.getTime() - date.getTime();
            const diffMins = Math.floor(diffMs / 60000);
            const diffHours = Math.floor(diffMs / 3600000);
            const diffDays = Math.floor(diffMs / 86400000);

            if (diffMins < 1) return 'Vừa xong';
            if (diffMins < 60) return `${diffMins} phút trước`;
            if (diffHours < 24) return `${diffHours} giờ trước`;
            if (diffDays < 7) return `${diffDays} ngày trước`;

            return date.toLocaleDateString('vi-VN', {
                day: '2-digit',
                month: '2-digit',
                year: 'numeric',
                hour: '2-digit',
                minute: '2-digit'
            });
        } catch (e) {
            return '';
        }
    };

    useEffect(() => {
        loadData();
        loadUserRating();
        loadComments();
        checkUserAuth();
    }, [loadData, loadUserRating, loadComments, checkUserAuth]);

    const handleRate = async (score: number) => {
        if (!id) return;
        console.log('Rating movie:', id, 'score:', score);
        try {
            await api.rateMovie(sessionId, parseInt(id, 10), score);
            setUserRating(score);
            // Re-fetch recommendations after rating
            const recsRes = await api.getRecommendations(sessionId, 10);
            setRecommended(recsRes.recommendations || []);
        } catch (e) {
            console.error('Failed to save rating:', e);
        }
    };

    const handleWatchMovie = async () => {
        if (!movie?.title) {
            Alert.alert("Lỗi", "Không thể lấy tên phim.");
            return;
        }

        try {
            // Lưu lịch sử xem phim
            const movieId = parseInt(id!);
            await api.saveWatchHistory(movieId, movie.title, movie.poster_path || movie.tmdb?.poster_path);
            // First try TMDB videos if available
            const videos = movie?.tmdb?.videos;
            if (videos && videos.length > 0) {
                const trailer = videos.find((v: any) => v.type === 'Trailer' && v.site === 'YouTube');
                const video = trailer || videos.find((v: any) => v.site === 'YouTube');
                
                if (video) {
                    // Play inline instead of opening YouTube
                    setActiveVideoId(video.key);
                    return;
                }
            }

            // If no TMDB video, search YouTube
            setMovieLoadingMessage("đang tải phim");
            let result;
            try {
                result = await api.searchYouTubeTrailer(movie.title, movie.tmdb?.release_date ? new Date(movie.tmdb.release_date).getFullYear() : undefined);
            } finally {
                setMovieLoadingMessage(null);
            }
            
            if (result && result.url) {
                const videoId = getYoutubeVideoId(result.url);
                if (videoId) {
                    setActiveVideoId(videoId);
                } else {
                    Alert.alert("Lỗi", "Không thể phát video này.");
                }
            } else {
                Alert.alert("Không tìm thấy", "Không tìm thấy trailer cho phim này.");
            }
        } catch (e) {
            console.error('Error searching trailer:', e);
            Alert.alert("Lỗi", "Có lỗi xảy ra khi tìm trailer.");
        }
    };

    const checkVipAccess = async (): Promise<boolean> => {
        // 1. Kiểm tra cột vip_movie của phim trực tiếp từ Supabase
        let isVipMovie = false;
        if (isTmdb !== 'true' && id) {
            try {
                const { data: dbMovie } = await supabase
                    .from('movie')
                    .select('vip_movie')
                    .eq('movie_id', parseInt(id))
                    .maybeSingle();

                if (dbMovie) {
                    isVipMovie = dbMovie.vip_movie || false;
                }
            } catch (e) {
                console.error("Lỗi truy vấn vip_movie:", e);
            }
        }

        // Nếu phim không phải phim VIP, cho xem bình thường
        if (!isVipMovie) {
            return true;
        }

        // 2. Phim là VIP nhưng chưa đăng nhập
        if (!currentUser) {
            Alert.alert("Yêu cầu VIP 🌟", "Phim này chỉ dành cho thành viên VIP. Vui lòng đăng nhập.");
            router.push('/log-in');
            return false;
        }

        try {
            // 3. Lấy trực tiếp thông tin VIP mới nhất từ Database để đảm bảo tính chính xác
            const { data: profile, error } = await supabase
                .from('profile')
                .select('vip_user, vip_expired_at')
                .eq('id', currentUser.id)
                .single();

            if (error || !profile) {
                Alert.alert("Lỗi", "Không thể kiểm tra thông tin tài khoản của bạn.");
                return false;
            }

            const isVip = profile.vip_user || false;
            const expiredAt = profile.vip_expired_at ? new Date(profile.vip_expired_at) : null;

            // 4. Nếu là VIP và VIP vẫn còn hạn sử dụng
            if (isVip && expiredAt && expiredAt > new Date()) {
                return true; 
            }

            // 5. Nếu vip_user đang là true nhưng ngày hết hạn đã quá hạn
            if (isVip) {
                // Tự động chuyển đổi vip_user thành false trên database
                await supabase
                    .from('profile')
                    .update({ vip_user: false })
                    .eq('id', currentUser.id);

                // Cập nhật lại UI state để ẩn các tính năng VIP
                setCurrentUser(prev => prev ? { ...prev, vip_user: false, vip_expired_at: null } : null);
            }

            // 6. Báo hết hạn và đưa ra lựa chọn mua VIP
            Alert.alert(
                "VIP đã hết hạn hoặc chưa đăng ký 🌟",
                "Phim này chỉ dành cho tài khoản VIP. Thời hạn VIP của bạn đã hết hoặc bạn chưa mua gói VIP. Vui lòng nâng cấp tài khoản để tiếp tục xem.",
                [
                    { text: "Để sau", style: "cancel" },
                    { text: "Nâng cấp VIP ngay", onPress: () => router.push('/profile' as any) }
                ]
            );
            return false;
        } catch (e) {
            console.error("Lỗi kiểm tra VIP:", e);
            Alert.alert("Lỗi", "Có lỗi xảy ra khi xác thực quyền VIP của bạn.");
            return false;
        }
    };

    const handleWatchFullMovie = async () => {
        // Kiểm tra quyền xem phim VIP trước khi xem phim
        const hasAccess = await checkVipAccess();
        if (!hasAccess) return;

        if (!movie?.title) {
            Alert.alert("Lỗi", "Không thể lấy tên phim.");
            return;
        }

        try {
            // Lưu lịch sử xem phim
            const movieId = parseInt(id!);
            await api.saveWatchHistory(movieId, movie.title, movie.poster_path || movie.tmdb?.poster_path);
            
            // First check watch providers from TMDB
            const providers = movie?.tmdb?.watch_providers;
            
            if (providers && Object.keys(providers).length > 0) {
                const region = providers.region || "US";
                const flatrate = providers.flatrate;
                const rent = providers.rent;
                const buy = providers.buy;
                const link = providers.link;

                if (flatrate || rent || buy) {
                    let options = ["Hủy"];
                    let providerInfo = `Xem phim ${movie.title}:\n\n`;

                    if (flatrate) {
                        providerInfo += `📺 Streaming:\n`;
                        flatrate.forEach((p: any) => {
                            providerInfo += `  • ${p.provider_name}\n`;
                        });
                        options.push("Streaming");
                    }

                    if (rent) {
                        providerInfo += `\n🎬 Thuê:\n`;
                        rent.forEach((p: any) => {
                            providerInfo += `  • ${p.provider_name}\n`;
                        });
                        options.push("Thuê");
                    }

                    if (buy) {
                        providerInfo += `\n🎁 Mua:\n`;
                        buy.forEach((p: any) => {
                            providerInfo += `  • ${p.provider_name}\n`;
                        });
                        options.push("Mua");
                    }

                    Alert.alert(
                        "Nơi xem phim",
                        providerInfo + `\n(Khu vực: ${region})`,
                        options.map((option) => ({
                            text: option,
                            onPress: () => {
                                if (option === "Hủy") return;
                                
                                if (link) {
                                    Linking.openURL(link).catch(() => {
                                        Alert.alert("Lỗi", "Không thể mở liên kết.");
                                    });
                                } else {
                                    let provider = "";
                                    if (option === "Streaming" && flatrate && flatrate.length > 0) {
                                        provider = flatrate[0].provider_name;
                                    } else if (option === "Thuê" && rent && rent.length > 0) {
                                        provider = rent[0].provider_name;
                                    } else if (option === "Mua" && buy && buy.length > 0) {
                                        provider = buy[0].provider_name;
                                    }

                                    if (provider.toLowerCase().includes("netflix")) {
                                        Linking.openURL("https://www.netflix.com").catch(() => {
                                            Alert.alert("Lỗi", "Không thể mở Netflix.");
                                        });
                                    } else if (provider.toLowerCase().includes("disney")) {
                                        Linking.openURL("https://www.disneyplus.com").catch(() => {
                                            Alert.alert("Lỗi", "Không thể mở Disney+.");
                                        });
                                    } else {
                                        const searchUrl = `https://www.google.com/search?q=${encodeURIComponent(movie.title + " " + provider)}`;
                                        Linking.openURL(searchUrl).catch(() => {
                                            Alert.alert("Lỗi", "Không thể mở Google.");
                                        });
                                    }
                                }
                            }
                        }))
                    );
                    return;
                }
            }

            // If no watch providers, search YouTube for full movie
            setMovieLoadingMessage("đang tải phim");
            let result;
            try {
                result = await api.searchYouTubeFullMovie(movie.title, movie.tmdb?.release_date ? new Date(movie.tmdb.release_date).getFullYear() : undefined);
            } finally {
                setMovieLoadingMessage(null);
            }
            
            if (result && result.url) {
                const videoId = getYoutubeVideoId(result.url);
                if (videoId) {
                    setActiveVideoId(videoId);
                } else {
                    // Fallback: open externally if we can't parse the video ID
                    Linking.openURL(result.url).catch(() => {
                        Alert.alert("Lỗi", "Không thể mở YouTube.");
                    });
                }
            } else {
                Alert.alert(
                    "Không tìm thấy",
                    "Không tìm thấy phim trên các nền tảng. Tìm trên Google?",
                    [
                        {
                            text: "Hủy",
                            onPress: () => {},
                            style: "cancel"
                        },
                        {
                            text: "Tìm trên Google",
                            onPress: () => {
                                const searchUrl = `https://www.google.com/search?q=${encodeURIComponent(movie.title + " watch online")}`;
                                Linking.openURL(searchUrl).catch(() => {
                                    Alert.alert("Lỗi", "Không thể mở Google.");
                                });
                            }
                        }
                    ]
                );
            }
        } catch (e) {
            console.error('Error searching full movie:', e);
            Alert.alert("Lỗi", "Có lỗi xảy ra khi tìm phim.");
        }
    };

    if (loading) {
        return (
            <View style={styles.center}>
                <ActivityIndicator size="large" color="#007AFF" />
            </View>
        );
    }

    if (!movie) {
        return (
            <View style={styles.center}>
                <Text style={{ color: '#fff', marginBottom: 15, fontSize: 16 }}>Không tìm thấy phim.</Text>
                <TouchableOpacity onPress={() => router.back()} style={styles.backButton}>
                    <Text style={{ color: '#fff', fontWeight: 'bold' }}>Quay lại</Text>
                </TouchableOpacity>
            </View>
        );
    }

    const getPosterUrl = () => {
        const path = movie.poster_path || movie.tmdb?.poster_path;
        if (!path) return "https://via.placeholder.com/500x750?text=No+Poster";
        if (path.startsWith('http')) return path;
        return `https://image.tmdb.org/t/p/w500${path}`;
    };

    const renderGenres = () => {
        const genres = movie.genres || movie.tmdb?.genres;
        if (!genres || !Array.isArray(genres)) return "Phổ thông";
        return genres.map((g: any) => typeof g === 'string' ? g : g.name).join(" • ");
    };

    const posterUrl = getPosterUrl();

    return (
        <>
            <ScrollView 
                style={styles.container} 
                showsVerticalScrollIndicator={false}
                contentContainerStyle={{ paddingBottom: insets.bottom + 20 }}
            >
                <View style={styles.posterContainer}>
                <Image source={{ uri: posterUrl }} style={styles.poster} />
                <LinearGradient
                    colors={['transparent', 'rgba(0,0,0,0.9)']}
                    style={styles.posterGradient}
                />
                <TouchableOpacity style={styles.floatingBackButton} onPress={() => router.back()}>
                    <Ionicons name="arrow-back" size={24} color="#fff" />
                </TouchableOpacity>
            </View>

            <View style={styles.content}>
                <View style={styles.mainInfo}>
                    <Text style={styles.title}>{movie.title}</Text>
                    <Text style={styles.genres}>{renderGenres()}</Text>
                    {(movie.vote_average !== undefined || movie.tmdb?.vote_average !== undefined) && (
                        <View style={styles.tmdbRating}>
                            <Ionicons name="star" size={16} color="#FFD700" />
                            <Text style={styles.tmdbRatingText}>
                                {(movie.vote_average || movie.tmdb?.vote_average || 0).toFixed(1)} / 10 (TMDB)
                            </Text>
                        </View>
                    )}
                </View>

                <View style={styles.ratingSection}>
                    <Text style={styles.sectionTitle}>Đánh giá của bạn</Text>
                    <View style={styles.stars}>
                        {[1, 2, 3, 4, 5].map((s) => (
                            <TouchableOpacity key={s} onPress={() => handleRate(s)}>
                                <Ionicons
                                    name={userRating >= s ? "star" : "star-outline"}
                                    size={40}
                                    color={userRating >= s ? "#FFD700" : "#ddd"}
                                    style={styles.starIcon}
                                />
                            </TouchableOpacity>
                        ))}
                    </View>
                    {userRating > 0 ? (
                        <Text style={styles.ratingStatus}>Bạn đã chấm {userRating}/5</Text>
                    ) : null}
                </View>

                <View style={styles.infoSection}>
                    <Text style={styles.sectionTitle}>Nội dung</Text>
                    <Text style={styles.overview}>
                        {movie.tmdb?.overview || movie.overview || "Chưa có thông tin nội dung phim."}
                    </Text>
                </View>

                {/* Watch Movie Button */}
                <View style={styles.watchSection}>
                    <View style={styles.watchButtonsContainer}>
                        <TouchableOpacity style={styles.watchButton} onPress={handleWatchMovie}>
                            <Ionicons name="play-circle" size={24} color="#fff" />
                            <Text style={styles.watchButtonText}>Xem Trailer</Text>
                        </TouchableOpacity>
                        <TouchableOpacity style={styles.watchFullButton} onPress={handleWatchFullMovie}>
                            <Ionicons name="film" size={24} color="#fff" />
                            <Text style={styles.watchButtonText}>Xem Phim</Text>
                        </TouchableOpacity>
                    </View>

                    {activeVideoId && (
                        <View style={styles.inlineVideoContainer}>
                            <YoutubePlayer
                                height={(width - 40) * 9 / 16}
                                videoId={activeVideoId}
                                play={true}
                                webViewStyle={{ opacity: 0.99 }}
                            />
                            <TouchableOpacity
                                style={styles.inlineCloseVideoButton}
                                onPress={() => setActiveVideoId(null)}
                            >
                                <Ionicons name="close-circle" size={20} color="#fff" />
                                <Text style={styles.inlineCloseVideoText}>Đóng video</Text>
                            </TouchableOpacity>
                        </View>
                    )}
                </View>

                {/* Section: Similar Movies */}
                {similar.length > 0 && (
                    <View style={styles.listSection}>
                        <Text style={styles.sectionTitle}>🎯 Phim tương tự</Text>
                        <FlatList
                            data={similar}
                            horizontal
                            showsHorizontalScrollIndicator={false}
                            renderItem={({ item }) => <MovieCard movie={item} />}
                            keyExtractor={(item) => `sim-${item.movie_id || item.id}`}
                            contentContainerStyle={styles.horizontalList}
                        />
                    </View>
                )}

                {/* Section: Recommended for You */}
                {recommended.length > 0 && (
                    <View style={styles.listSection}>
                        <Text style={styles.sectionTitle}>✨ Có thể bạn sẽ thích (AI)</Text>
                        <FlatList
                            data={recommended}
                            horizontal
                            showsHorizontalScrollIndicator={false}
                            renderItem={({ item }) => <MovieCard movie={item} />}
                            keyExtractor={(item) => `rec-${item.movie_id || item.id}`}
                            contentContainerStyle={styles.horizontalList}
                        />
                    </View>
                )}

                {/* Phần bình luận */}
                <View style={styles.commentSection}>
                    <View style={styles.commentHeader}>
                        <Text style={styles.sectionTitle}>💬 Bình luận ({comments.length})</Text>
                        <TouchableOpacity onPress={loadComments} disabled={commentsLoading}>
                            {commentsLoading ? (
                                <ActivityIndicator size="small" color="#007AFF" />
                            ) : (
                                <Ionicons name="refresh-outline" size={20} color="#007AFF" />
                            )}
                        </TouchableOpacity>
                    </View>

                    {/* Ô viết bình luận */}
                    {currentUser ? (
                        <View style={styles.writeCommentContainer}>
                            <TextInput
                                style={styles.commentInput}
                                placeholder="Chia sẻ cảm nghĩ của bạn về bộ phim..."
                                placeholderTextColor="#999"
                                value={newCommentText}
                                onChangeText={setNewCommentText}
                                multiline
                                maxLength={500}
                            />
                            <View style={styles.writeCommentFooter}>
                                <Text style={styles.charCount}>
                                    {newCommentText.length}/500 ký tự
                                </Text>
                                <TouchableOpacity 
                                    style={[
                                        styles.sendButton,
                                        (!newCommentText.trim() || commentSubmitting) && styles.sendButtonDisabled
                                    ]}
                                    onPress={handleAddComment}
                                    disabled={!newCommentText.trim() || commentSubmitting}
                                >
                                    {commentSubmitting ? (
                                        <ActivityIndicator size="small" color="#fff" />
                                    ) : (
                                        <View style={{ flexDirection: 'row', alignItems: 'center' }}>
                                            <Ionicons name="send" size={14} color="#fff" />
                                            <Text style={styles.sendButtonText}>Gửi</Text>
                                        </View>
                                    )}
                                </TouchableOpacity>
                            </View>
                        </View>
                    ) : (
                        <View style={styles.loginRequiredBox}>
                            <Ionicons name="chatbubble-ellipses-outline" size={32} color="#007AFF" style={{ marginBottom: 8 }} />
                            <Text style={styles.loginRequiredText}>
                                Bạn cần đăng nhập để viết bình luận cho bộ phim này.
                            </Text>
                            <TouchableOpacity 
                                style={styles.loginBtn}
                                onPress={() => router.push('/log-in')}
                            >
                                <Text style={styles.loginBtnText}>Đăng nhập ngay</Text>
                            </TouchableOpacity>
                        </View>
                    )}

                    {/* Danh sách bình luận */}
                    {commentsLoading && comments.length === 0 ? (
                        <View style={styles.commentsLoader}>
                            <ActivityIndicator size="small" color="#007AFF" />
                            <Text style={styles.loaderText}>Đang tải bình luận...</Text>
                        </View>
                    ) : comments.length > 0 ? (
                        <View style={styles.commentsList}>
                            {comments.map((item) => (
                                <View key={item.id} style={styles.commentItem}>
                                    <View style={styles.commentItemHeader}>
                                        <View style={styles.commentAuthorRow}>
                                            <View style={styles.commentAvatar}>
                                                <Text style={styles.commentAvatarText}>
                                                    {item.user_name ? item.user_name.charAt(0).toUpperCase() : 'U'}
                                                </Text>
                                            </View>
                                            <View style={styles.commentAuthorInfo}>
                                                <Text style={styles.commentAuthorName}>{item.user_name}</Text>
                                                <Text style={styles.commentTime}>{formatCommentDate(item.created_at)}</Text>
                                            </View>
                                        </View>
                                        {currentUser && currentUser.id === item.user_id && (
                                            <TouchableOpacity 
                                                style={styles.deleteCommentBtn}
                                                onPress={() => handleDeleteComment(item.id)}
                                            >
                                                <Ionicons name="trash-outline" size={18} color="#ff4d4d" />
                                            </TouchableOpacity>
                                        )}
                                    </View>
                                    <Text style={styles.commentContent}>{item.content}</Text>
                                </View>
                            ))}
                        </View>
                    ) : (
                        <View style={styles.emptyCommentsContainer}>
                            <Ionicons name="chatbubbles-outline" size={48} color="#ccc" style={{ marginBottom: 12 }} />
                            <Text style={styles.emptyCommentsText}>
                                Chưa có bình luận nào cho phim này. Hãy là người đầu tiên chia sẻ ý kiến nhé!
                            </Text>
                        </View>
                    )}
                </View>
            </View>
        </ScrollView>

        <Modal
            transparent={true}
            visible={movieLoadingMessage !== null}
            animationType="fade"
        >
            <View style={styles.modalBackground}>
                <View style={styles.loadingModalContainer}>
                    <ActivityIndicator size="large" color="#007AFF" />
                    <Text style={styles.loadingModalText}>{movieLoadingMessage}</Text>
                </View>
            </View>
        </Modal>
    </>
);
}

const styles = StyleSheet.create({
    container: {
        flex: 1,
        backgroundColor: '#121212',
    },
    center: {
        flex: 1,
        justifyContent: 'center',
        alignItems: 'center',
        minHeight: 300,
        backgroundColor: '#121212',
    },
    posterContainer: {
        width: '100%',
        height: 500,
        position: 'relative',
    },
    videoContainer: {
        width: '100%',
        backgroundColor: '#000',
        position: 'relative',
    },
    poster: {
        width: '100%',
        height: '100%',
    },
    posterGradient: {
        position: 'absolute',
        bottom: 0,
        left: 0,
        right: 0,
        height: 200,
    },
    floatingBackButton: {
        position: 'absolute',
        top: 50,
        left: 20,
        width: 40,
        height: 40,
        borderRadius: 20,
        backgroundColor: 'rgba(0,0,0,0.5)',
        justifyContent: 'center',
        alignItems: 'center',
    },
    closeVideoButton: {
        position: 'absolute',
        top: 10,
        right: 10,
        zIndex: 10,
    },
    content: {
        padding: 20,
        marginTop: -40,
    },
    mainInfo: {
        marginBottom: 24,
    },
    title: {
        fontSize: 28,
        fontWeight: 'bold',
        color: '#fff',
        textShadowColor: 'rgba(0, 0, 0, 0.75)',
        textShadowOffset: { width: -1, height: 1 },
        textShadowRadius: 10,
    },
    genres: {
        fontSize: 16,
        color: 'rgba(255,255,255,0.9)',
        marginTop: 6,
        fontWeight: '500',
    },
    tmdbRating: {
        flexDirection: 'row',
        alignItems: 'center',
        marginTop: 12,
        backgroundColor: 'rgba(255,255,255,0.2)',
        paddingHorizontal: 10,
        paddingVertical: 4,
        borderRadius: 12,
        alignSelf: 'flex-start',
    },
    tmdbRatingText: {
        color: '#fff',
        marginLeft: 6,
        fontSize: 14,
        fontWeight: 'bold',
    },
    ratingSection: {
        backgroundColor: '#1e1e1e',
        borderRadius: 20,
        padding: 20,
        alignItems: 'center',
        marginBottom: 24,
        borderWidth: 1,
        borderColor: '#333',
    },
    sectionTitle: {
        fontSize: 20,
        fontWeight: 'bold',
        marginBottom: 16,
        color: '#fff',
    },
    stars: {
        flexDirection: 'row',
    },
    starIcon: {
        marginHorizontal: 4,
    },
    ratingStatus: {
        marginTop: 12,
        fontSize: 15,
        color: '#007AFF',
        fontWeight: '600',
    },
    infoSection: {
        marginBottom: 30,
    },
    overview: {
        fontSize: 16,
        lineHeight: 24,
        color: '#ddd',
    },
    watchSection: {
        marginBottom: 30,
        alignItems: 'center',
        width: '100%',
    },
    watchButtonsContainer: {
        flexDirection: 'row',
        justifyContent: 'space-around',
        width: '100%',
    },
    inlineVideoContainer: {
        width: '100%',
        backgroundColor: '#000',
        borderRadius: 12,
        overflow: 'hidden',
        marginTop: 16,
        paddingBottom: 4,
        borderWidth: 1,
        borderColor: '#333',
    },
    inlineCloseVideoButton: {
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'center',
        paddingVertical: 10,
        backgroundColor: '#222',
        borderTopWidth: 1,
        borderTopColor: '#333',
    },
    inlineCloseVideoText: {
        color: '#fff',
        fontWeight: 'bold',
        marginLeft: 8,
        fontSize: 14,
    },
    watchButton: {
        backgroundColor: '#FF0000', // YouTube red
        flexDirection: 'row',
        alignItems: 'center',
        paddingHorizontal: 20,
        paddingVertical: 12,
        borderRadius: 25,
        shadowColor: '#000',
        shadowOffset: { width: 0, height: 2 },
        shadowOpacity: 0.3,
        shadowRadius: 4,
        elevation: 5,
        flex: 1,
        marginHorizontal: 5,
    },
    watchFullButton: {
        backgroundColor: '#007AFF', // Blue for full movie
        flexDirection: 'row',
        alignItems: 'center',
        paddingHorizontal: 20,
        paddingVertical: 12,
        borderRadius: 25,
        shadowColor: '#000',
        shadowOffset: { width: 0, height: 2 },
        shadowOpacity: 0.3,
        shadowRadius: 4,
        elevation: 5,
        flex: 1,
        marginHorizontal: 5,
    },
    watchButtonText: {
        color: '#fff',
        fontSize: 16,
        fontWeight: 'bold',
        marginLeft: 8,
    },
    listSection: {
        marginBottom: 30,
    },
    horizontalList: {
        paddingBottom: 10,
    },
    backButton: {
        marginTop: 20,
        backgroundColor: '#007AFF',
        paddingHorizontal: 20,
        paddingVertical: 10,
        borderRadius: 20,
    },
    commentSection: {
        marginTop: 20,
        borderTopWidth: 1,
        borderTopColor: '#222',
        paddingTop: 24,
        paddingBottom: 40,
    },
    commentHeader: {
        flexDirection: 'row',
        justifyContent: 'space-between',
        alignItems: 'center',
        marginBottom: 16,
    },
    writeCommentContainer: {
        backgroundColor: '#1e1e1e',
        borderRadius: 16,
        padding: 12,
        marginBottom: 20,
        borderWidth: 1,
        borderColor: '#333',
    },
    commentInput: {
        fontSize: 15,
        color: '#fff',
        minHeight: 80,
        textAlignVertical: 'top',
        padding: 8,
    },
    writeCommentFooter: {
        flexDirection: 'row',
        justifyContent: 'space-between',
        alignItems: 'center',
        borderTopWidth: 1,
        borderTopColor: '#333',
        paddingTop: 8,
        marginTop: 8,
    },
    charCount: {
        fontSize: 12,
        color: '#999',
    },
    sendButton: {
        backgroundColor: '#007AFF',
        flexDirection: 'row',
        alignItems: 'center',
        paddingHorizontal: 16,
        paddingVertical: 8,
        borderRadius: 20,
    },
    sendButtonDisabled: {
        backgroundColor: '#ccc',
    },
    sendButtonText: {
        color: '#fff',
        fontWeight: 'bold',
        marginLeft: 6,
        fontSize: 14,
    },
    loginRequiredBox: {
        backgroundColor: '#1a1a1a',
        borderRadius: 16,
        padding: 20,
        alignItems: 'center',
        marginBottom: 20,
        borderWidth: 1,
        borderColor: '#333',
    },
    loginRequiredText: {
        fontSize: 14,
        color: '#aaa',
        textAlign: 'center',
        marginBottom: 12,
        lineHeight: 20,
    },
    loginBtn: {
        backgroundColor: '#007AFF',
        paddingHorizontal: 20,
        paddingVertical: 10,
        borderRadius: 20,
    },
    loginBtnText: {
        color: '#fff',
        fontWeight: 'bold',
        fontSize: 14,
    },
    commentsLoader: {
        alignItems: 'center',
        paddingVertical: 20,
    },
    loaderText: {
        marginTop: 8,
        color: '#666',
        fontSize: 14,
    },
    commentsList: {
        marginTop: 10,
    },
    commentItem: {
        paddingVertical: 16,
        borderBottomWidth: 1,
        borderBottomColor: '#222',
    },
    commentItemHeader: {
        flexDirection: 'row',
        justifyContent: 'space-between',
        alignItems: 'center',
        marginBottom: 8,
    },
    commentAuthorRow: {
        flexDirection: 'row',
        alignItems: 'center',
    },
    commentAvatar: {
        width: 36,
        height: 36,
        borderRadius: 18,
        backgroundColor: '#007AFF',
        justifyContent: 'center',
        alignItems: 'center',
        marginRight: 10,
    },
    commentAvatarText: {
        color: '#fff',
        fontSize: 16,
        fontWeight: 'bold',
    },
    commentAuthorInfo: {
        justifyContent: 'center',
    },
    commentAuthorName: {
        fontSize: 14,
        fontWeight: 'bold',
        color: '#fff',
    },
    commentTime: {
        fontSize: 11,
        color: '#999',
        marginTop: 2,
    },
    deleteCommentBtn: {
        padding: 4,
    },
    commentContent: {
        fontSize: 14,
        color: '#eee',
        lineHeight: 20,
        paddingLeft: 46,
    },
    emptyCommentsContainer: {
        alignItems: 'center',
        paddingVertical: 40,
    },
    emptyCommentsText: {
        fontSize: 14,
        color: '#999',
        textAlign: 'center',
        lineHeight: 22,
        paddingHorizontal: 20,
    },
    modalBackground: {
        flex: 1,
        alignItems: 'center',
        justifyContent: 'center',
        backgroundColor: 'rgba(0, 0, 0, 0.7)',
    },
    loadingModalContainer: {
        backgroundColor: '#1e1e1e',
        padding: 24,
        borderRadius: 16,
        alignItems: 'center',
        borderWidth: 1,
        borderColor: '#333',
        minWidth: 180,
    },
    loadingModalText: {
        color: '#fff',
        marginTop: 15,
        fontSize: 16,
        fontWeight: '600',
    },
});
