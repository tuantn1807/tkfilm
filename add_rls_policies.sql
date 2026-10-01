-- ============================================
-- 🔐 Thêm RLS Policies cho Supabase Service Role
-- ============================================
-- Chạy file này ở Supabase Dashboard:
-- 1. Vào: https://app.supabase.com/project/kzcsegvlfaebwpxipqxx
-- 2. SQL Editor → New Query
-- 3. Copy-paste tất cả code dưới đây
-- 4. Click "Run"
-- ============================================

-- ============================================
-- 1. POLICIES CHO BẢNG "profile"
-- ============================================

-- Policy cho service_role SELECT (để lấy thông tin profile)
CREATE POLICY "service_role can select profile" ON public.profile
  FOR SELECT TO service_role
  USING (true);

-- Policy cho service_role UPDATE (để cập nhật vip_user, vip_expired_at)
CREATE POLICY "service_role can update profile" ON public.profile
  FOR UPDATE TO service_role
  USING (true)
  WITH CHECK (true);

-- ============================================
-- 2. POLICIES CHO BẢNG "vip_transactions"
-- ============================================

-- Policy cho service_role thực hiện mọi hành động (SELECT, INSERT, UPDATE, DELETE)
CREATE POLICY "service_role can manage transactions" ON public.vip_transactions
  FOR ALL TO service_role
  USING (true)
  WITH CHECK (true);

-- ============================================
-- XONG! Các policies đã được thêm.
-- Bây giờ hãy test lại VNPay.
-- ============================================
