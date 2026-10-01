# 🔐 Hướng dẫn thêm VNPay Secrets vào Supabase

## ⚠️ QUAN TRỌNG: Phải thêm secrets TRƯỚC khi deploy!

Supabase Edge Functions cần các biến môi trường (secrets) để chạy. Nếu không thêm secrets, function sẽ báo lỗi.

---

## 📋 Danh sách Secrets cần thêm

| Key | Value |
|-----|-------|
| `VNP_TMN_CODE` | `LAGRKMON` |
| `VNP_HASH_SECRET` | `OKBI50STRIDCCODAT29GWACA96J3XZSG` |
| `VNP_PAY_URL` | `https://sandbox.vnpayment.vn/paymentv2/vpcpay.html` |
| `VNP_RETURN_URL` | `https://kzcsegvlfaebwpxipqxx.supabase.co/functions/v1/vnpay/payment-return` |
| `VNP_IPN_URL` | `https://kzcsegvlfaebwpxipqxx.supabase.co/functions/v1/vnpay/payment-ipn` |

---

## ✅ Cách 1: Thêm Secrets qua Supabase Dashboard (Khuyến nghị)

### Bước 1: Vào Supabase Dashboard
1. Mở https://app.supabase.com
2. Đăng nhập với tài khoản của bạn

### Bước 2: Chọn Project
- Tìm và click vào project: **kzcsegvlfaebwpxipqxx**

### Bước 3: Vào Settings
- Click **Settings** (bánh răng ⚙️) ở thanh sidebar bên trái
- Scroll xuống tìm **Edge Functions**
- Click vào **Edge Functions**

### Bước 4: Thêm Secrets
1. Tìm section **Secrets**
2. Click nút **+ New Secret** (hoặc **Add Secret**)
3. Điền thông tin:
   - **Key**: `VNP_TMN_CODE`
   - **Value**: `LAGRKMON`
4. Click **Save Secret**

### Bước 5: Lặp lại Bước 4 cho các secrets còn lại
- `VNP_HASH_SECRET` = `OKBI50STRIDCCODAT29GWACA96J3XZSG`
- `VNP_PAY_URL` = `https://sandbox.vnpayment.vn/paymentv2/vpcpay.html`
- `VNP_RETURN_URL` = `https://kzcsegvlfaebwpxipqxx.supabase.co/functions/v1/vnpay/payment-return`
- `VNP_IPN_URL` = `https://kzcsegvlfaebwpxipqxx.supabase.co/functions/v1/vnpay/payment-ipn`

---

## ✅ Cách 2: Thêm Secrets qua Supabase CLI

### Bước 1: Mở PowerShell/Terminal

### Bước 2: Chạy script (Cách nhanh nhất)
```powershell
cd c:\Users\Admin\Downloads\tkfilm\supabase\functions\vnpay
.\add-vnpay-secrets.ps1
```

### Bước 3: Hoặc thêm thủ công từng secret
```powershell
supabase secrets set VNP_TMN_CODE LAGRKMON --project-id kzcsegvlfaebwpxipqxx
supabase secrets set VNP_HASH_SECRET OKBI50STRIDCCODAT29GWACA96J3XZSG --project-id kzcsegvlfaebwpxipqxx
supabase secrets set VNP_PAY_URL https://sandbox.vnpayment.vn/paymentv2/vpcpay.html --project-id kzcsegvlfaebwpxipqxx
supabase secrets set VNP_RETURN_URL https://kzcsegvlfaebwpxipqxx.supabase.co/functions/v1/vnpay/payment-return --project-id kzcsegvlfaebwpxipqxx
supabase secrets set VNP_IPN_URL https://kzcsegvlfaebwpxipqxx.supabase.co/functions/v1/vnpay/payment-ipn --project-id kzcsegvlfaebwpxipqxx
```

---

## 🧪 Kiểm tra Secrets đã được thêm

### Qua Dashboard:
1. Vào Settings → Edge Functions → Secrets
2. Bạn sẽ thấy danh sách các secrets (values sẽ bị ẩn vì bảo mật)

### Qua CLI:
```powershell
supabase secrets list --project-id kzcsegvlfaebwpxipqxx
```

---

## 🚀 Deploy Edge Function

Sau khi thêm xong tất cả secrets, deploy function:

```powershell
cd c:\Users\Admin\Downloads\tkfilm
supabase functions deploy vnpay --project-id kzcsegvlfaebwpxipqxx
```

**Output mong đợi:**
```
✓ Function deployed successfully!
✓ Available at https://kzcsegvlfaebwpxipqxx.supabase.co/functions/v1/vnpay
```

---

## ❓ Troubleshooting

### ❌ "Function deployed but payment fails with UNAUTHORIZED"
**Nguyên nhân**: Secrets không được thêm đúng hoặc RLS policy bị chặn

**Giải pháp**:
1. Kiểm tra lại secrets (xem section trên)
2. Kiểm tra RLS Policy (xem hướng dẫn trong VNPAY_FIX_GUIDE.md)

### ❌ "vip_user vẫn không update"
**Nguyên nhân**: `VNP_IPN_URL` chưa được VNPay gọi

**Giải pháp**:
1. Kiểm tra VNP_IPN_URL được set đúng chưa
2. Vào Function Logs xem có request nào đến endpoint `/payment-ipn` không
3. Nếu không có, check logs ở VNPay dashboard

### ❌ "Script PowerShell báo lỗi permission denied"
**Giải pháp**:
```powershell
# Cho phép chạy script
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

---

## 📚 Tài liệu thêm
- [Supabase Edge Functions Secrets](https://supabase.com/docs/guides/functions/secrets)
- [Supabase CLI](https://supabase.com/docs/guides/cli/getting-started)
- [VNPay Integration](https://sandbox.vnpayment.vn/apis/documentation/)
