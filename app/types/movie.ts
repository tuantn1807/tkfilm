export interface Movie {
    id: string | number;
    movie_id?: number;
    vip_movie?: boolean;

    title: string;
    genres: string[];
    rating: number;
    poster_path: string;
    release_date?: string;
    overview?: string;
    score?: number;
    vote_average?: number;
    tmdb?: any;
}
