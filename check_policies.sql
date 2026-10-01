-- Kiểm tra RLS policies trên bảng profile
SELECT schemaname, tablename, policyname, permissive, roles, qual, with_check 
FROM pg_policies 
WHERE tablename = 'profile' AND policyname LIKE '%service%';

-- Kiểm tra RLS policies trên bảng vip_transactions
SELECT schemaname, tablename, policyname, permissive, roles, qual, with_check 
FROM pg_policies 
WHERE tablename = 'vip_transactions' AND policyname LIKE '%service%';
