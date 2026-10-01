import { Platform } from 'react-native';
import { supabase } from '../../supabase';

// ============ IMPORTANT: Update this IP to your computer's IP address ============
// Find your IP: On Windows, run 'ipconfig' in terminal and look for "IPv4 Address"
// For Expo Go on physical device: Use your computer's local IP (e.g., 192.168.1.x)
// For emulator: Use 10.0.2.2 (Android) or localhost (iOS)
// For physical device, set EXPO_PUBLIC_BACKEND_URL to your machine IP (for example: http://192.168.88.154:5000)
const DEFAULT_BACKEND_URL = Platform.select({
    android: 'http://172.22.171.190:5000',
    ios: 'http://127.0.0.1:5000',
    default: 'http://127.0.0.1:5000',
});

export const BACKEND_URL = process.env.EXPO_PUBLIC_BACKEND_URL ?? DEFAULT_BACKEND_URL ?? 'http://172.22.171.190:5000';

// ============================================================================

// Helper function to safely parse JSON and log errors
const safeJsonParse = async (
    response: Response,
    endpoint: string,
    options?: { suppressHttpErrorLog?: boolean }
) => {
    try {
        if (!response) {
            if (!options?.suppressHttpErrorLog) console.error(`[API] Empty response for ${endpoint}`);
            return null;
        }

        let contentType: string | null = null;
        let text: string = '';
        try {
            contentType = response.headers?.get ? response.headers.get('content-type') : null;
        } catch (e) {
            contentType = null;
        }

        try {
            const t = await response.text();
            text = typeof t === 'string' ? t : String(t || '');
        } catch (e) {
            text = '';
        }

        try {
            console.log(`[API] Endpoint: ${endpoint}`);
            console.log(`[API] Status: ${response && (response as any).status}`);
            console.log(`[API] Content-Type: ${contentType}`);
            console.log(`[API] Response text: ${text ? text.substring(0, 200) : '<empty>'}`);
        } catch (e) {
            // swallow logging errors
        }

        if (!response.ok) {
            if (!options?.suppressHttpErrorLog) {
                try {
                    console.error(`[API] HTTP Error ${response && (response as any).status}: ${text}`);
                } catch (e) {
                    console.error('[API] HTTP Error, failed to stringify response');
                }
            }
            return null;
        }

        if (!contentType || !contentType.includes('application/json')) {
            if (!options?.suppressHttpErrorLog) console.error(`[API] Response is not JSON: ${contentType}`);
            return null;
        }

        try {
            return JSON.parse(text || '{}');
        } catch (e: any) {
            console.error(`[API] JSON parse error for ${endpoint}:`, e?.message || e);
            return null;
        }
    } catch (e: any) {
        console.error(`[API] Unexpected parse error for ${endpoint}:`, e?.message || e);
        return null;
    }
};

export const api = {
    getRecommendations: async (sessionId: string, topK = 20) => {
        try {
            // Try to include Supabase user UUID if available so server can use persisted ratings
            const { data: sessionData } = await supabase.auth.getSession();
            const userUuid = sessionData?.session?.user?.id;

            const payload: any = { session_id: sessionId, top_k: topK };
            if (userUuid) payload.supabase_user_id = userUuid;

            const resp = await fetch(`${BACKEND_URL}/api/recommend`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            const data = await safeJsonParse(resp, '/api/recommend');
            return data || { recommendations: [] };
        } catch (e) {
            console.error('API Error:', e);
            return { recommendations: [] };
        }
    },

    getRecommendationsByGenres: async (genres: string[], topN = 10) => {
        try {
            const genresStr = genres.join(',');
            const resp = await fetch(`${BACKEND_URL}/api/recommend_coldstart?genres=${genresStr}&top_n=${topN}`);
            const data = await safeJsonParse(resp, '/api/recommend_coldstart');
            return data || { results: [] };
        } catch (e) {
            console.error('API Error:', e);
            return { results: [] };
        }
    },

    getSimilarMovies: async (movieIds: string[], topN = 10) => {
        try {
            const idsStr = movieIds.join(',');
            const resp = await fetch(`${BACKEND_URL}/api/recommend_from_movies?movie_ids=${idsStr}&top_n=${topN}`);
            return await resp.json();
        } catch (e) {
            console.error('API Error:', e);
            return { results: [] };
        }
    },

    getMovieDetails: async (movieId: number) => {
        try {
            const resp = await fetch(`${BACKEND_URL}/api/movie/${movieId}/tmdb`);
            return await resp.json();
        } catch (e) {
            console.error('API Error:', e);
            return null;
        }
    },

    savePreferences: async (sessionId: string, favoriteGenres: string[]) => {
        try {
            const resp = await fetch(`${BACKEND_URL}/api/preferences`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ session_id: sessionId, favorite_genres: favoriteGenres }),
            });
            return await resp.json();
        } catch (e) {
            console.error('API Error:', e);
            return { success: false };
        }
    },

    rateMovie: async (sessionId: string, movieId: number, rating: number) => {
        try {
            const isMovieLensMovieId = Number.isInteger(movieId) && movieId >= 0 && movieId < 1682;
            const { data: sessionData, error: sessionError } = await supabase.auth.getSession();
            if (sessionError) {
                console.error('Supabase auth session error:', sessionError);
            }
            const userId = sessionData?.session?.user?.id;
            console.debug('[API] rateMovie called', { sessionId, movieId, rating, supabaseUserId: userId });
            if (userId) {
                if (!isMovieLensMovieId) {
                    console.warn('[API] Skipping Supabase rating sync for non-MovieLens movie id', { movieId });
                } else {

                    const { data: existing, error: selectError } = await supabase
                        .from('rating')
                        .select('id,user_uuid,user_id,item_id,rating')
                        .eq('user_uuid', userId)
                        .eq('item_id', movieId)
                        .limit(1)
                        .single();

                    if (selectError && selectError.code !== 'PGRST116') {
                        console.error('Supabase lookup rating error:', selectError);
                    }

                    if (existing?.id) {
                        const { error: updateError } = await supabase
                            .from('rating')
                            .update({ rating: rating })
                            .eq('id', existing.id);

                        if (updateError) {
                            console.error('Supabase update rating error:', updateError);
                        } else {
                            console.debug('[API] Updated existing rating row', { id: existing.id });
                        }
                    } else {
                        let { error: insertError } = await supabase
                            .from('rating')
                            .insert([{ user_uuid: userId, item_id: movieId, rating: rating }]);

                        if (insertError) {
                            console.error('Supabase insert rating error:', insertError);

                            // If foreign key constraint fails because the movie row is missing,
                            // attempt to insert a minimal movie row and retry once.
                            try {
                                if (insertError.code === '23503') {
                                    console.debug('[API] Detected missing movie FK, attempting to insert minimal movie row', { movieId });

                                    // Try to insert a minimal movie record into `movie` table to satisfy FK.
                                    const minimalMovie = { movie_id: movieId, movie_title: `ML ${movieId}` };
                                    const { error: movieInsertError } = await supabase.from('movie').insert([minimalMovie]);
                                    if (movieInsertError) {
                                        console.error('Supabase insert minimal movie error:', movieInsertError);
                                    } else {
                                        console.debug('[API] Inserted minimal movie row', { movieId });
                                        // Retry rating insert once
                                        const { error: retryError } = await supabase
                                            .from('rating')
                                            .insert([{ user_uuid: userId, item_id: movieId, rating: rating }]);
                                        if (retryError) {
                                            console.error('Supabase retry insert rating error:', retryError);
                                        } else {
                                            console.debug('[API] Inserted new rating row after inserting minimal movie', { movieId, rating });
                                            insertError = null;
                                        }
                                    }
                                }
                            } catch (e: any) {
                                console.error('Error handling FK insert failure:', e);
                            }
                        } else {
                            console.debug('[API] Inserted new rating row', { movieId, rating });
                        }
                    }
                }
            }

            if (!isMovieLensMovieId) {
                return { success: true, skipped_backend_sync: true };
            }

            const resp = await fetch(`${BACKEND_URL}/api/rate`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ session_id: sessionId, movie_id: movieId, rating }),
            });
            const data = await safeJsonParse(resp, '/api/rate');
            return data || { success: false };
        } catch (e) {
            console.error('API Error:', e);
            return { success: false };
        }
    },

    getPopularMovies: async () => {
        try {
            const resp = await fetch(`${BACKEND_URL}/api/movies/top_rated?top_k=20`);
            const data = await safeJsonParse(resp, '/api/movies/top_rated', { suppressHttpErrorLog: true });
            if (data) return data;

            // Fallback to TMDB popular
            const resp2 = await fetch(`${BACKEND_URL}/api/tmdb/popular`);
            const data2 = await safeJsonParse(resp2, '/api/tmdb/popular');
            return data2 || { results: [] };
        } catch (e) {
            console.error('API Error:', e);
            return { results: [] };
        }
    },

    getMoviesByGenre: async (genre: string, page = 1, perPage = 20) => {
        try {
            const resp = await fetch(`${BACKEND_URL}/api/movies?genre=${encodeURIComponent(genre)}&page=${page}&per_page=${perPage}&enrich=true`);
            return await resp.json();
        } catch (e) {
            console.error('API Error:', e);
            return { movies: [] };
        }
    },

    getUserStatus: async (sessionId: string) => {
        try {
            const { data: sessionData } = await supabase.auth.getSession();
            const userUuid = sessionData?.session?.user?.id;
            const url = new URL(`${BACKEND_URL}/api/user/status/${sessionId}`);
            if (userUuid) url.searchParams.set('supabase_user_id', userUuid);
            const resp = await fetch(url.toString());
            return await resp.json();
        } catch (e) {
            console.error('API Error:', e);
            return { rating_count: 0, onboarded: false };
        }
    },

    resetUserData: async (sessionId: string) => {
        try {
            const { data: sessionData } = await supabase.auth.getSession();
            const userUuid = sessionData?.session?.user?.id;

            if (!userUuid) {
                return { success: false };
            }

            // Call server-side endpoint that uses SUPABASE_SERVICE_KEY to delete rows
            const resp = await fetch(`${BACKEND_URL}/api/user/reset`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ supabase_user_id: userUuid }),
            });

            const data = await safeJsonParse(resp, '/api/user/reset');
            return data || { success: false };
        } catch (e) {
            console.error('API Error:', e);
            return { success: false };
        }
    },

    getSimilarMoviesItemToItem: async (movieId: number, topK = 10) => {
        try {
            const resp = await fetch(`${BACKEND_URL}/api/movies/similar/${movieId}?top_k=${topK}`);
            return await resp.json();
        } catch (e) {
            console.error('API Error:', e);
            return { results: [] };
        }
    },

    getOnboardingMovies: async (limit = 20) => {
        try {
            const resp = await fetch(`${BACKEND_URL}/api/movies/onboarding?limit=${limit}`);
            return await resp.json();
        } catch (e) {
            console.error('API Error:', e);
            return { movies: [] };
        }
    },

    getUserRatings: async (sessionId?: string) => {
        try {
            const sessionResp = await supabase.auth.getSession();
            const userUuid = sessionResp.data.session?.user?.id;
            console.debug('[API] getUserRatings called', { sessionId, supabaseSession: !!sessionResp.data.session, supabaseUserId: userUuid });

            if (!userUuid) {
                console.debug('[API] getUserRatings: no supabase user id, returning empty');
                return { ratings: [] };
            }

            // Select additional columns to help debug schema mismatches (user_id vs user_uuid)
            const { data, error } = await supabase
                .from('rating')
                .select('item_id, rating, user_uuid, user_id');

            if (error) {
                console.error('Supabase getUserRatings error:', error);
                return { ratings: [] };
            }

            // Filter rows matching either user_uuid or user_id (string compare) to capture legacy rows
            const rows = (data || []).filter((r: any) => {
                return (r.user_uuid && r.user_uuid === userUuid) || (r.user_id && String(r.user_id) === String(userUuid));
            });

            console.debug('[API] getUserRatings: fetched rows count', { totalRows: (data || []).length, matchedRows: rows.length });

            return {
                ratings: rows.map((item: any) => ({
                    movie_id: item.item_id?.toString(),
                    rating: Number(item.rating),
                })),
            };
        } catch (e) {
            console.error('API Error:', e);
            return { ratings: [] };
        }
    },

    searchMovies: async (query: string) => {
        try {
            const resp = await fetch(`${BACKEND_URL}/api/tmdb/search?query=${encodeURIComponent(query)}`);
            return await resp.json();
        } catch (e) {
            console.error('API Error:', e);
            return { results: [] };
        }
    },

    getTmdbMovieDetails: async (tmdbId: number) => {
        try {
            const resp = await fetch(`${BACKEND_URL}/api/tmdb/movie/${tmdbId}`);
            return await resp.json();
        } catch (e) {
            console.error('API Error:', e);
            return null;
        }
    },

    getGenres: async () => {
        try {
            const resp = await fetch(`${BACKEND_URL}/api/genres`);
            const data = await safeJsonParse(resp, '/api/genres');
            return data || { genres: [] };
        } catch (e) {
            console.error('API Error:', e);
            return { genres: [] };
        }
    },

    searchYouTubeTrailer: async (movieTitle: string, year?: number) => {
        try {
            let url = `${BACKEND_URL}/api/youtube/search/trailer/${encodeURIComponent(movieTitle)}`;
            if (year) {
                url += `?year=${year}`;
            }
            const resp = await fetch(url);
            return await resp.json();
        } catch (e) {
            console.error('API Error:', e);
            return null;
        }
    },

    searchYouTubeFullMovie: async (movieTitle: string, year?: number) => {
        try {
            let url = `${BACKEND_URL}/api/youtube/search/movie/${encodeURIComponent(movieTitle)}`;
            if (year) {
                url += `?year=${year}`;
            }
            const resp = await fetch(url);
            return await resp.json();
        } catch (e) {
            console.error('API Error:', e);
            return null;
        }
    },

    // Lưu lịch sử xem phim
    saveWatchHistory: async (movieId: number, movieTitle?: string, posterPath?: string) => {
        try {
            const { data: sessionData, error: sessionError } = await supabase.auth.getSession();
            if (sessionError || !sessionData?.session?.user?.id) {
                console.warn('Cannot save watch history: not authenticated');
                return { success: false };
            }

            const userId = sessionData.session.user.id;

            // Upsert: nếu đã xem phim này rồi, cập nhật thời gian; nếu chưa, thêm mới
            const { error } = await supabase
                .from('watch_history')
                .upsert(
                    {
                        user_id: userId,
                        movie_id: movieId,
                        watched_at: new Date().toISOString(),
                    },
                    { onConflict: 'user_id,movie_id' }
                );

            if (error) {
                console.error('Supabase saveWatchHistory error:', error);
                return { success: false };
            }

            return { success: true };
        } catch (e) {
            console.error('API Error saveWatchHistory:', e);
            return { success: false };
        }
    },

    // Lấy lịch sử xem phim
    getWatchHistory: async () => {
        try {
            const { data: sessionData, error: sessionError } = await supabase.auth.getSession();
            if (sessionError || !sessionData?.session?.user?.id) {
                console.warn('Cannot get watch history: not authenticated');
                return { watch_history: [] };
            }

            const userId = sessionData.session.user.id;

            const { data, error } = await supabase
                .from('watch_history')
                .select('movie_id, watched_at')
                .eq('user_id', userId)
                .order('watched_at', { ascending: false });

            if (error) {
                console.error('Supabase getWatchHistory error:', error);
                return { watch_history: [] };
            }

            return {
                watch_history: (data || []).map((item: any) => ({
                    movie_id: item.movie_id?.toString(),
                    watched_at: item.watched_at,
                })),
            };
        } catch (e) {
            console.error('API Error getWatchHistory:', e);
            return { watch_history: [] };
        }
    },

    // Lấy danh sách bình luận của phim kèm theo tên người dùng
    getMovieComments: async (movieId: number) => {
        try {
            const { data, error } = await supabase
                .from('movie_comment')
                .select(`
                    id,
                    movie_id,
                    user_id,
                    content,
                    created_at,
                    profile:profile(name)
                `)
                .eq('movie_id', movieId)
                .order('created_at', { ascending: false });

            if (error) {
                console.error('Supabase getMovieComments error:', error);
                return { comments: [] };
            }

            return {
                comments: (data || []).map((item: any) => ({
                    id: item.id,
                    movie_id: item.movie_id,
                    user_id: item.user_id,
                    content: item.content,
                    created_at: item.created_at,
                    user_name: item.profile?.name || 'Người dùng ẩn danh',
                })),
            };
        } catch (e) {
            console.error('API Error getMovieComments:', e);
            return { comments: [] };
        }
    },

    // Thêm bình luận mới cho phim
    addMovieComment: async (movieId: number, content: string) => {
        try {
            const { data: sessionData, error: sessionError } = await supabase.auth.getSession();
            if (sessionError || !sessionData?.session?.user?.id) {
                console.warn('Cannot add comment: not authenticated');
                return { success: false, error: 'Chưa đăng nhập' };
            }

            const userId = sessionData.session.user.id;

            const { data, error } = await supabase
                .from('movie_comment')
                .insert([
                    {
                        movie_id: movieId,
                        user_id: userId,
                        content: content.trim(),
                    }
                ])
                .select(`
                    id,
                    movie_id,
                    user_id,
                    content,
                    created_at,
                    profile:profile(name)
                `)
                .single();

            if (error) {
                console.error('Supabase addMovieComment error:', error);
                return { success: false, error: error.message };
            }

            return {
                success: true,
                comment: {
                    id: data.id,
                    movie_id: data.movie_id,
                    user_id: data.user_id,
                    content: data.content,
                    created_at: data.created_at,
                    user_name: data.profile?.name || 'Người dùng ẩn danh',
                }
            };
        } catch (e: any) {
            console.error('API Error addMovieComment:', e);
            return { success: false, error: e?.message || 'Có lỗi xảy ra' };
        }
    },

    // Xoá bình luận
    deleteMovieComment: async (commentId: string) => {
        try {
            const { data: sessionData, error: sessionError } = await supabase.auth.getSession();
            if (sessionError || !sessionData?.session?.user?.id) {
                console.warn('Cannot delete comment: not authenticated');
                return { success: false, error: 'Chưa đăng nhập' };
            }

            const userId = sessionData.session.user.id;

            const { error } = await supabase
                .from('movie_comment')
                .delete()
                .eq('id', commentId)
                .eq('user_id', userId);

            if (error) {
                console.error('Supabase deleteMovieComment error:', error);
                return { success: false, error: error.message };
            }

            return { success: true };
        } catch (e: any) {
            console.error('API Error deleteMovieComment:', e);
            return { success: false, error: e?.message || 'Có lỗi xảy ra' };
        }
    },

    createVnpayPayment: async (amount: number, orderId: string, packageType: string) => {
        try {
            const { data: sessionData } = await supabase.auth.getSession();
            const userId = sessionData?.session?.user?.id;

            if (!userId) {
                console.warn('[API] Chưa đăng nhập tài khoản');
                return { status: 'error', message: 'Vui lòng đăng nhập để thanh toán' };
            }

            console.debug('[API] Gọi Edge Function vnpay', { amount, orderId, userId, packageType });

            const { data, error } = await supabase.functions.invoke('vnpay', {
                body: {
                    amount: amount,
                    order_id: orderId,
                    user_id: userId,
                    package_type: packageType
                }
            });

            if (error) {
                console.error('[API] Lỗi gọi Edge Function:', error);
                return { status: 'error', message: error.message };
            }

            // IN URL RA TERMINAL METRO BUNDLER ĐỂ KIỂM TRA
            console.log("=== URL THANH TOÁN sinh ra là ===", data?.payment_url);

            return data;
        } catch (e: any) {
            console.error('[API] Lỗi bất ngờ createVnpayPayment:', e);
            return { status: 'error', message: e?.message || 'Có lỗi xảy ra' };
        }
    }
};
