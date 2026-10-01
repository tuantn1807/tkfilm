#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import glob
import math
import numpy as np
import torch
from data import load_dataset
from settings import MOVIE_LENS_100k_DATASET_PATH

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def _latest_file(pattern):
    files = glob.glob(os.path.join(BASE_DIR, pattern))
    return max(files, key=os.path.getmtime) if files else None

def ndcg_at_k(relevant, ranked, k):
    ranked = ranked[:k]
    rel = [1.0 if x in relevant else 0.0 for x in ranked]
    ideal = sorted(rel, reverse=True)
    dcg = lambda r: sum((2**x - 1) / math.log2(i + 2) for i, x in enumerate(r))
    idcg = dcg(ideal)
    return 0.0 if idcg == 0 else dcg(rel) / idcg

def evaluate_embeddings(users_emb_path, movies_emb_path, train_matrix, test_matrix, k_list=[5, 10, 20], threshold=4.0):
    if not users_emb_path or not movies_emb_path:
        return None
        
    users_emb = torch.load(users_emb_path, map_location="cpu").float()
    movies_emb = torch.load(movies_emb_path, map_location="cpu").float()
    
    # L2 Normalization for Cosine Similarity
    users_emb = users_emb / (users_emb.norm(dim=1, keepdim=True) + 1e-8)
    movies_emb = movies_emb / (movies_emb.norm(dim=1, keepdim=True) + 1e-8)
    
    precisions = {k: [] for k in k_list}
    recalls = {k: [] for k in k_list}
    ndcgs = {k: [] for k in k_list}
    
    for u in range(train_matrix.size(0)):
        train_items = (train_matrix[u] > 0).nonzero().view(-1).tolist()
        test_ratings = test_matrix[u]
        
        relevant_items = (test_ratings >= threshold).nonzero().view(-1).tolist()
        if len(relevant_items) == 0:
            continue
            
        # Cosine Similarity between user vector and all movie vectors
        # users_emb[u] shape: (D,), movies_emb shape: (N, D)
        scores = torch.mv(movies_emb, users_emb[u]).detach().cpu().numpy()
        
        # Mask out train items
        scores[train_items] = -1e9
        ranked = np.argsort(-scores)
        
        for k in k_list:
            topk = ranked[:k]
            hits = len(set(topk) & set(relevant_items))
            
            precisions[k].append(hits / k)
            recalls[k].append(hits / len(relevant_items))
            ndcgs[k].append(ndcg_at_k(relevant_items, topk, k))
            
    results = {}
    for k in k_list:
        results[k] = {
            "P": np.mean(precisions[k]),
            "R": np.mean(recalls[k]),
            "NDCG": np.mean(ndcgs[k])
        }
    return results

def main():
    print("==================================================================")
    print("   SO SÁNH HIỆU NĂNG NHÚNG: STANDARD AUTOENCODER vs. RSAttAE      ")
    print("==================================================================")
    
    # 1. Load data
    train_df, val_df, test_df, train_matrix, val_matrix, test_matrix, users_feat, movies_feat = load_dataset(
        MOVIE_LENS_100k_DATASET_PATH,
        split=1,
        val_size=0.15,
    )
    
    # Combined train for retrieval scoring
    train_matrix_combined = train_matrix.float() + val_matrix.float()
    
    # Find files
    std_users = _latest_file("users_embeddings_autoencoder_*.pt")
    std_movies = _latest_file("movies_embeddings_autoencoder_*.pt")
    
    att_users = _latest_file("users_embeddings_attention_autoencoder_*.pt")
    att_movies = _latest_file("movies_embeddings_attention_autoencoder_*.pt")
    
    missing_std = not std_users or not std_movies
    missing_att = not att_users or not att_movies
    
    if missing_std or missing_att:
        print("\n[!] CẢNH BÁO: Thiếu file trọng số nhúng để thực hiện so sánh.")
        if missing_std:
            print(" -> Thiếu nhúng Autoencoder truyền thống. Vui lòng chạy:")
            print("    python train_user_autoencoder.py")
            print("    python train_movie_autoencoder.py")
        if missing_att:
            print(" -> Thiếu nhúng Attention Autoencoder. Vui lòng chạy:")
            print("    python train_user_attention_autoencoder.py")
            print("    python train_movie_attention_autoencoder.py")
        print("\nSau khi huấn luyện xong cả hai, hãy chạy lại script này.")
        return
        
    print(f" Tải nhúng Autoencoder cơ bản: \n  - User: {os.path.basename(std_users)}\n  - Movie: {os.path.basename(std_movies)}")
    print(f" Tải nhúng Attention Autoencoder (RSAttAE): \n  - User: {os.path.basename(att_users)}\n  - Movie: {os.path.basename(att_movies)}")
    
    k_list = [5, 10, 20]
    
    print("\n Đang tính toán đánh giá mô hình bằng Cosine Similarity...")
    std_results = evaluate_embeddings(std_users, std_movies, train_matrix_combined, test_matrix, k_list=k_list)
    att_results = evaluate_embeddings(att_users, att_movies, train_matrix_combined, test_matrix, k_list=k_list)
    
    print("\n======================= BẢNG SO SÁNH KẾT QUẢ =======================")
    print(f"{'Metric':<10} | {'Autoencoder (Baseline)':<22} | {'RSAttAE (Attention)':<20} | {'Cải thiện (%)':<15}")
    print("-" * 75)
    
    for k in k_list:
        for metric in ["P", "R", "NDCG"]:
            metric_name = f"{metric}@{k}"
            std_val = std_results[k][metric]
            att_val = att_results[k][metric]
            
            diff_pct = ((att_val - std_val) / (std_val + 1e-8)) * 100
            diff_str = f"+{diff_pct:.2f}%" if diff_pct >= 0 else f"{diff_pct:.2f}%"
            
            print(f"{metric_name:<10} | {std_val:<22.4f} | {att_val:<20.4f} | {diff_str:<15}")
        print("-" * 75)
        
    print("\n[💡] Nhận xét:")
    print(" - Precision@K đo lường tỷ lệ gợi ý chính xác trong danh sách Top-K.")
    print(" - Recall@K đo lường độ phủ của danh sách gợi ý so với toàn bộ phim user thích ở tập test.")
    print(" - NDCG@K đo lường chất lượng xếp hạng của danh sách gợi ý (đánh giá thứ tự phim tốt lên đầu).")
    print("==================================================================")

if __name__ == "__main__":
    main()
