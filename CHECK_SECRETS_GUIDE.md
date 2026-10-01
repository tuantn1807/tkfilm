# ✅ Hướng dẫn Kiểm tra Secrets đã được thêm chưa

## 🎯 Mục đích
Kiểm tra xem 5 secrets VNPay đã được thêm vào Supabase chưa.

---

## 📋 Cách kiểm tra bằng Supabase Dashboard (Dễ nhất)

### Bước 1: Vào Supabase Dashboard
- Truy cập: https://app.supabase.com
- Đăng nhập tài khoản của bạn

### Bước 2: Chọn Project
- Click vào project: **kzcsegvlfaebwpxipqxx**

### Bước 3: Vào Settings
- Click biểu tượng **Cog** (⚙️) ở thanh sidebar bên trái
- Chọn **Settings**

### Bước 4: Tìm Edge Functions → Secrets
- Scroll xuống tìm section **Edge Functions**
- Click vào **Edge Functions**
- Tìm subsection **Secrets**

### Bước 5: Kiểm tra danh sách Secrets
Bạn sẽ thấy một bảng với danh sách secrets. **Cần tìm thấy 5 secrets sau:**

| # | Tên Secret | Trạng thái |
|---|-----------|----------|
| 1 | `VNP_TMN_CODE` | ✅ Phải có |
| 2 | `VNP_HASH_SECRET` | ✅ Phải có |
| 3 | `VNP_PAY_URL` | ✅ Phải có |
| 4 | `VNP_RETURN_URL` | ✅ Phải có |
| 5 | `VNP_IPN_URL` | ✅ Phải có |

**Lưu ý**: Giá trị (value) của secrets sẽ bị ẩn vì bảo mật (chỉ thấy `•••`), nhưng tên phải hiển thị rõ.

---

## ❌ Nếu thiếu secrets

### Nếu thiếu 1 hoặc nhiều secrets:

1. Click nút **+ Add Secret** (hoặc **New Secret**)
2. Điền:
   - **Key**: Tên secret (ví dụ: `VNP_TMN_CODE`)
   - **Value**: Giá trị tương ứng (xem bảng dưới)
3. Click **Save** hoặc **Add Secret**

### Giá trị của 5 secrets:

```
VNP_TMN_CODE = LAGRKMON

VNP_HASH_SECRET = OKBI50STRIDCCODAT29GWACA96J3XZSG

VNP_PAY_URL = https://sandbox.vnpayment.vn/paymentv2/vpcpay.html

VNP_RETURN_URL = https://kzcsegvlfaebwpxipqxx.supabase.co/functions/v1/vnpay/payment-return

VNP_IPN_URL = https://kzcsegvlfaebwpxipqxx.supabase.co/functions/v1/vnpay/payment-ipn
```

---

## ✅ Sau khi kiểm tra xong

1. **Tất cả 5 secrets có** → ✅ OK! Có thể code ở Antigravity
2. **Thiếu secrets** → Thêm các secrets còn thiếu rồi test lại

---

## 🎯 Kiểm tra Edge Function đã deploy chưa

Cùng lúc kiểm tra secrets, hãy xem Function có deployed không:

1. Ở Supabase Dashboard, vào **Functions** (thanh sidebar bên trái)
2. Tìm function: **vnpay**
3. Xem status:
   - ✅ **Active** = Hàm đã sẵn sàng sử dụng
   - ❌ **Error** hoặc không thấy = Cần deploy lại

---

## 📝 Checklist hoàn tất

Sau khi kiểm tra xong, tick vào:

- [ ] Tất cả 5 secrets có sẵn ở Supabase Dashboard
- [ ] Function `vnpay` có status **Active**
- [ ] RLS Policies đã được thêm (nếu không báo lỗi "already exists")
- [ ] Sẵn sàng code ở Antigravity

---

## 💡 Tips cho coding ở Antigravity

Khi code ở Antigravity, các variables từ Supabase Secrets sẽ **tự động** có sẵn:
- `Deno.env.get("VNP_TMN_CODE")`
- `Deno.env.get("VNP_HASH_SECRET")`
- Etc.

**Không cần** code manual lấy từ `.env` file!

---

## ❓ Troubleshooting

### Q: Secrets không hiển thị ở Dashboard?
**A**: 
1. Refresh trang (Ctrl+F5)
2. Logout rồi login lại
3. Kiểm tra có phải admin project không

### Q: Function báo Error?
**A**: 
1. Click vào function xem **Logs** tab
2. Tìm message lỗi chi tiết
3. Có thể do secrets chưa được inject đúng

### Q: Vẫn báo UNAUTHORIZED?
**A**: 
1. Kiểm tra RLS Policies (xem file add_rls_policies.sql)
2. Kiểm tra `SUPABASE_SERVICE_ROLE_KEY` có trong secrets không
