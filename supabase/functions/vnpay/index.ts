// supabase/functions/vnpay/index.ts

/**
 * ============================================
 * 🔐 HƯỚNG DẪN CẤU HÌNH SECRETS
 * ============================================
 * 
 * TRƯỚC KHI DEPLOY, bạn PHẢI thêm các secrets sau vào Supabase:
 * 
 * 1. Vào: https://app.supabase.com
 * 2. Chọn project: kzcsegvlfaebwpxipqxx
 * 3. Vào: Settings → Edge Functions → Secrets
 * 4. Thêm các secrets sau:
 * 
 *    - VNP_TMN_CODE = LAGRKMON
 *    - VNP_HASH_SECRET = OKBI50STRIDCCODAT29GWACA96J3XZSG
 *    - VNP_PAY_URL = https://sandbox.vnpayment.vn/paymentv2/vpcpay.html
 *    - VNP_RETURN_URL = https://kzcsegvlfaebwpxipqxx.supabase.co/functions/v1/vnpay/payment-return
 *    - VNP_IPN_URL = https://kzcsegvlfaebwpxipqxx.supabase.co/functions/v1/vnpay/payment-ipn
 * 
 * 5. Sau khi thêm secrets, deploy function:
 *    supabase functions deploy vnpay --project-id kzcsegvlfaebwpxipqxx
 * 
 * ============================================
 */

import { serve } from "https://deno.land/std@0.168.0/http/server.ts"
import { createClient } from "https://esm.sh/@supabase/supabase-js@2.39.0"

// -------------------------------------------------------------
// 1. CẤU HÌNH CORS ĐỂ APP EXPO / FRONTEND CÓ THỂ GỌI ĐƯỢC
// -------------------------------------------------------------
const corsHeaders = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Headers': 'authorization, x-client-info, apikey, content-type',
  'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
}

// -------------------------------------------------------------
// 2. HÀM HỖ TRỢ BĂM CHỮ KÝ HMAC-SHA512 DÙNG NATIVE WEB CRYPTO
// -------------------------------------------------------------
async function hmacSha512(key: string, data: string): Promise<string> {
  const encoder = new TextEncoder();
  const cryptoKey = await crypto.subtle.importKey(
    "raw",
    encoder.encode(key),
    { name: "HMAC", hash: "SHA-512" },
    false,
    ["sign"]
  );
  const signature = await crypto.subtle.sign(
    "HMAC",
    cryptoKey,
    encoder.encode(data)
  );
  return Array.from(new Uint8Array(signature))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

// Helper function to encode URL parameters according to VNPay standard (spaces as +)
function vnpayEncode(str: string): string {
  return encodeURIComponent(str).replace(/%20/g, "+");
}

// -------------------------------------------------------------
// 3. DIỂM KHỞI CHẠY CHÍNH CỦA EDGE FUNCTION (MAIN HANDLER)
// -------------------------------------------------------------
serve(async (req) => {
  // Xử lý request CORS Preflight (trình duyệt hoặc thiết bị check quyền)
  if (req.method === 'OPTIONS') {
    return new Response('ok', { headers: corsHeaders })
  }

  const url = new URL(req.url);
  const path = url.pathname; // Ví dụ: "/vnpay/create-payment" hoặc "/vnpay/payment-ipn"

  // Đọc các biến môi trường cấu hình VNPay trong Supabase Secrets
  const VNP_TMN_CODE = (Deno.env.get("VNP_TMN_CODE") || "").trim();
  const VNP_HASH_SECRET = (Deno.env.get("VNP_HASH_SECRET") || "").trim();
  const VNP_PAY_URL = (Deno.env.get("VNP_PAY_URL") || "https://sandbox.vnpayment.vn/paymentv2/vpcpay.html").trim();
  const VNP_RETURN_URL = (Deno.env.get("VNP_RETURN_URL") || "").trim(); // VD: https://<ref>.supabase.co/functions/v1/vnpay/payment-return

  // Khởi tạo Supabase client sử dụng Service Role Key để có quyền ghi đè RLS (cập nhật trạng thái)
  const supabaseClient = createClient(
    Deno.env.get('SUPABASE_URL') ?? '',
    Deno.env.get('SUPABASE_SERVICE_ROLE_KEY') ?? ''
  );

  try {
    // =========================================================
    // ROUTE 1: TẠO URL THANH TOÁN (POST /vnpay/create-payment hoặc POST /vnpay)
    // =========================================================
    if (req.method === "POST" && (path.endsWith("/create-payment") || path.endsWith("/vnpay"))) {
      const body = await req.json();
      const { amount, order_id, user_id, package_type } = body;

      if (!amount || !order_id || !user_id || !package_type) {
        return new Response(
          JSON.stringify({ status: "error", message: "Thiếu thông tin yêu cầu" }),
          { status: 400, headers: { ...corsHeaders, "Content-Type": "application/json" } }
        );
      }

      // A. Tạo hoặc cập nhật bản ghi giao dịch trong bảng vip_transactions của bạn ở trạng thái 'pending'
      const { error: dbError } = await supabaseClient
        .from("vip_transactions")
        .upsert({
          order_id: order_id,
          user_id: user_id,
          amount: amount,
          package_type: package_type,
          status: "pending",
          created_at: new Date().toISOString()
        }, { onConflict: "order_id" });

      if (dbError) {
        throw new Error(`Lỗi khởi tạo giao dịch trong DB: ${dbError.message}`);
      }

      // B. Thiết lập các thông số gửi sang VNPay
      const vnp_amount = amount * 100; // Nhân 100 theo quy định VNPay
      
      // Lấy thời gian hiện tại và cộng 7 giờ để chuyển đổi sang múi giờ Việt Nam (GMT+7)
      const now = new Date();
      const vnTime = new Date(now.getTime() + 7 * 60 * 60 * 1000);
      const createDate = vnTime.toISOString().replace(/T/, '').replace(/\..+/, '').replace(/-|:/g, ''); // Định dạng: yyyyMMddHHmmss
      
      const vnpayParams: Record<string, string> = {
        "vnp_Version": "2.1.0",
        "vnp_Command": "pay",
        "vnp_TmnCode": VNP_TMN_CODE,
        "vnp_Amount": vnp_amount.toString(),
        "vnp_CreateDate": createDate,
        "vnp_CurrCode": "VND",
        "vnp_IpAddr": "127.0.0.1",
        "vnp_Locale": "vn",
        "vnp_OrderInfo": `Thanh toan goi ${package_type}`,
        "vnp_OrderType": "billpayment",
        "vnp_ReturnUrl": VNP_RETURN_URL,
        "vnp_TxnRef": order_id
      };

      // C. Sắp xếp tham số theo bảng chữ cái alphabet
      const sortedKeys = Object.keys(vnpayParams).sort();
      const hashParts: string[] = [];
      const queryParts: string[] = [];

      for (const key of sortedKeys) {
        const encodedKey = vnpayEncode(key);
        const encodedVal = vnpayEncode(vnpayParams[key]);
        hashParts.push(`${encodedKey}=${encodedVal}`);
        queryParts.push(`${encodedKey}=${encodedVal}`);
      }

      const hashData = hashParts.join("&");
      const queryString = queryParts.join("&");

      // D. Tính toán chữ ký bảo mật SHA-512
      const secureHash = await hmacSha512(VNP_HASH_SECRET, hashData);

      // E. Sinh URL thanh toán hoàn chỉnh
      const paymentUrl = `${VNP_PAY_URL}?${queryString}&vnp_SecureHash=${secureHash}`;

      return new Response(
        JSON.stringify({ status: "success", payment_url: paymentUrl }),
        { status: 200, headers: { ...corsHeaders, "Content-Type": "application/json" } }
      );
    }

    // =========================================================
    // ROUTE 2: NHẬN THÔNG BÁO TỪ VNPAY (GET /vnpay/payment-ipn)
    // =========================================================
    if (req.method === "GET" && path.endsWith("/payment-ipn")) {
      const params = Object.fromEntries(url.searchParams.entries());
      const vnp_SecureHash = params["vnp_SecureHash"];

      if (!vnp_SecureHash) {
        return new Response(JSON.stringify({ RspCode: "97", Message: "Missing secure hash" }), { headers: corsHeaders });
      }

      // Loại bỏ tham số hash để tính toán lại đối soát
      const cleanParams = { ...params };
      delete cleanParams["vnp_SecureHash"];
      delete cleanParams["vnp_SecureHashType"];

      // Sắp xếp tham số phản hồi
      const sortedKeys = Object.keys(cleanParams).sort();
      const hashParts = sortedKeys.map(key => `${vnpayEncode(key)}=${vnpayEncode(cleanParams[key])}`);
      const hashData = hashParts.join("&");

      const calculatedHash = await hmacSha512(VNP_HASH_SECRET, hashData);

      // So khớp chữ ký
      if (calculatedHash.toLowerCase() !== vnp_SecureHash.toLowerCase()) {
        return new Response(JSON.stringify({ RspCode: "97", Message: "Invalid Signature" }), { headers: corsHeaders });
      }

      const txnRef = params["vnp_TxnRef"];
      const vnp_Amount = params["vnp_Amount"];
      const responseCode = params["vnp_ResponseCode"];

      // 1. Kiểm tra đơn hàng có tồn tại trong bảng vip_transactions của bạn không
      const { data: dbTxn, error: fetchErr } = await supabaseClient
        .from("vip_transactions")
        .select("*")
        .eq("order_id", txnRef)
        .maybeSingle();

      if (fetchErr || !dbTxn) {
        return new Response(JSON.stringify({ RspCode: "01", Message: "Order not found" }), { headers: corsHeaders });
      }

      // 2. Kiểm tra số tiền khớp không
      const dbAmount = Number(dbTxn.amount);
      const vnpayAmount = Number(vnp_Amount) / 100;
      if (dbAmount !== vnpayAmount) {
        return new Response(JSON.stringify({ RspCode: "04", Message: "Invalid Amount" }), { headers: corsHeaders });
      }

      // 3. Kiểm tra trạng thái đơn hàng đã được cập nhật trước đó chưa
      if (dbTxn.status !== "pending") {
        return new Response(JSON.stringify({ RspCode: "02", Message: "Order already confirmed" }), { headers: corsHeaders });
      }

      // Cập nhật Database dựa trên kết quả giao dịch
      if (responseCode === "00") {
        // Giao dịch thành công
        // A. Cập nhật bảng vip_transactions thành 'success' và lưu thời gian paid_at
        await supabaseClient
          .from("vip_transactions")
          .update({ status: "success", paid_at: new Date().toISOString() })
          .eq("order_id", txnRef);

        // B. Nâng cấp role của user thành 'premium', vip_user: true và tính toán vip_expired_at trong bảng profile
        if (dbTxn.user_id) {
          // 1. Lấy thông tin profile hiện tại để kiểm tra thời hạn VIP cũ
          const { data: profileData } = await supabaseClient
            .from("profile")
            .select("vip_user, vip_expired_at")
            .eq("id", dbTxn.user_id)
            .maybeSingle();

          let baseDate = new Date();
          if (profileData && profileData.vip_expired_at) {
            const currentExpiredAt = new Date(profileData.vip_expired_at);
            // Nếu VIP cũ chưa hết hạn, ta cộng dồn tiếp nối từ hạn cũ
            if (currentExpiredAt > new Date()) {
              baseDate = currentExpiredAt;
            }
          }

          // 2. Tính số tháng cộng thêm dựa trên gói mua (1 tháng, 6 tháng, 1 năm)
          const packageType = dbTxn.package_type;
          let monthsToAdd = 1;
          if (packageType === "6_months") {
            monthsToAdd = 6;
          } else if (packageType === "1_year") {
            monthsToAdd = 12;
          }

          // Cộng thêm tháng
          const newExpiredAt = new Date(baseDate);
          newExpiredAt.setMonth(newExpiredAt.getMonth() + monthsToAdd);

          // 3. Cập nhật bảng profile
          await supabaseClient
            .from("profile")
            .update({ 
              role: "premium",
              vip_user: true,
              vip_expired_at: newExpiredAt.toISOString()
            })
            .eq("id", dbTxn.user_id);
        }
      } else {
        // Giao dịch thất bại hoặc bị hủy
        await supabaseClient
          .from("vip_transactions")
          .update({ status: "failed" })
          .eq("order_id", txnRef);
      }

      return new Response(JSON.stringify({ RspCode: "00", Message: "Confirm Success" }), { headers: corsHeaders });
    }

    // =========================================================
    // ROUTE 3: HIỂN THỊ KẾT QUẢ CHO NGƯỜI DÙNG (GET /vnpay/payment-return)
    // =========================================================
    if (req.method === "GET" && path.endsWith("/payment-return")) {
      const params = Object.fromEntries(url.searchParams.entries());
      const vnp_SecureHash = params["vnp_SecureHash"];

      const cleanParams = { ...params };
      delete cleanParams["vnp_SecureHash"];
      delete cleanParams["vnp_SecureHashType"];

      const sortedKeys = Object.keys(cleanParams).sort();
      const hashParts = sortedKeys.map(key => `${vnpayEncode(key)}=${vnpayEncode(cleanParams[key])}`);
      const hashData = hashParts.join("&");

      const calculatedHash = await hmacSha512(VNP_HASH_SECRET, hashData);

      let status = "failed";
      let message = "Thanh toán thất bại";
      const txnRef = params["vnp_TxnRef"] || "N/A";
      const amount = Number(params["vnp_Amount"] || 0) / 100;

      if (calculatedHash.toLowerCase() === vnp_SecureHash?.toLowerCase() && params["vnp_ResponseCode"] === "00") {
        status = "success";
        message = "Thanh toán thành công!";

        // Cập nhật database ngay tại đây đề phòng trường hợp cuộc gọi IPN của VNPay bị lỗi/chặn
        try {
          const { data: dbTxn } = await supabaseClient
            .from("vip_transactions")
            .select("*")
            .eq("order_id", txnRef)
            .maybeSingle();

          if (dbTxn && dbTxn.status === "pending") {
            // A. Cập nhật vip_transactions thành success
            await supabaseClient
              .from("vip_transactions")
              .update({ status: "success", paid_at: new Date().toISOString() })
              .eq("order_id", txnRef);

            // B. Nâng cấp vip_user và thời hạn vip_expired_at trong profile
            if (dbTxn.user_id) {
              const { data: profileData } = await supabaseClient
                .from("profile")
                .select("vip_user, vip_expired_at")
                .eq("id", dbTxn.user_id)
                .maybeSingle();

              let baseDate = new Date();
              if (profileData && profileData.vip_expired_at) {
                const currentExpiredAt = new Date(profileData.vip_expired_at);
                if (currentExpiredAt > new Date()) {
                  baseDate = currentExpiredAt;
                }
              }

              const packageType = dbTxn.package_type;
              let monthsToAdd = 1;
              if (packageType === "6_months") {
                monthsToAdd = 6;
              } else if (packageType === "1_year") {
                monthsToAdd = 12;
              }

              const newExpiredAt = new Date(baseDate);
              newExpiredAt.setMonth(newExpiredAt.getMonth() + monthsToAdd);

              await supabaseClient
                .from("profile")
                .update({ 
                  role: "premium",
                  vip_user: true,
                  vip_expired_at: newExpiredAt.toISOString()
                })
                .eq("id", dbTxn.user_id);
            }
          }
        } catch (dbErr) {
          console.error("Lỗi cập nhật DB trong payment-return:", dbErr);
        }
      } else if (calculatedHash.toLowerCase() === vnp_SecureHash?.toLowerCase()) {
        // Giao dịch bị hủy hoặc thất bại
        try {
          await supabaseClient
            .from("vip_transactions")
            .update({ status: "failed" })
            .eq("order_id", txnRef);
        } catch (dbErr) {
          console.error("Lỗi cập nhật trạng thái thất bại:", dbErr);
        }
      }

      // Trả về HTML Dark-Mode chất lượng cao cho trình duyệt
      const html = `
        <!DOCTYPE html>
        <html>
        <head>
            <title>Kết quả giao dịch</title>
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <style>
                body { font-family: -apple-system, sans-serif; text-align: center; padding: 60px 20px; background: #121212; color: #fff; }
                .card { background: #1e1e1e; padding: 40px 30px; border-radius: 16px; max-width: 400px; margin: 0 auto; border: 1px solid #2e2e2e; }
                .icon { font-size: 64px; margin-bottom: 20px; }
                .success { color: #4CAF50; }
                .failed { color: #E50914; }
                .btn { display: inline-block; margin-top: 25px; padding: 12px 28px; background: #E50914; color: white; text-decoration: none; border-radius: 8px; font-weight: bold; }
                .redirect-text { font-size: 13px; color: #999; margin-top: 15px; }
            </style>
        </head>
        <body>
            <div class="card">
                <div class="icon ${status === 'success' ? 'success' : 'failed'}">
                    ${status === 'success' ? '✓' : '✕'}
                </div>
                <h2 class="${status === 'success' ? 'success' : 'failed'}">${message}</h2>
                <p>Mã đơn hàng: <strong>${txnRef}</strong></p>
                <p>Số tiền: <strong>${amount.toLocaleString('vi-VN')} VND</strong></p>
                <a href="tkfilm://payment-result?status=${status}&txn_ref=${txnRef}" class="btn">Quay lại ứng dụng</a>
                <p class="redirect-text">Tự động quay lại ứng dụng sau 2 giây...</p>
            </div>
            <script>
                // Tự động chuyển hướng quay lại app điện thoại
                setTimeout(function() {
                    window.location.href = "tkfilm://payment-result?status=${status}&txn_ref=${txnRef}";
                }, 2000);
            </script>
        </body>
        </html>
      `;

      return new Response(html, {
        headers: new Headers({
          "content-type": "text/html; charset=utf-8",
        })
      });
    }

    // Không khớp bất kỳ Route nào
    return new Response(JSON.stringify({ error: "Not Found" }), { status: 404, headers: corsHeaders });

  } catch (err) {
    return new Response(
      JSON.stringify({ error: err.message }),
      { status: 500, headers: { ...corsHeaders, "Content-Type": "application/json" } }
    );
  }
});
