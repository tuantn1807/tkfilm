from flask import Blueprint, request, jsonify, redirect
from flask import render_template_string
import os
import hashlib
import hmac
import urllib.parse
from datetime import datetime

import requests

def _supabase_request(method: str, table: str, params=None, json_data=None):
    """Hàm helper để gọi nhanh tới database Supabase từ Flask"""
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_KEY")
    
    if not supabase_url or not supabase_key:
        raise RuntimeError("Chưa cấu hình Supabase URL hoặc Key trong file .env")

    url = f"{supabase_url}/rest/v1/{table}"
    headers = {
        "apikey": supabase_key,
        "Authorization": f"Bearer {supabase_key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation"
    }
    
    response = requests.request(method, url, headers=headers, params=params, json=json_data, timeout=10)
    response.raise_for_status()
    return response.json()


vnpay_bp = Blueprint('vnpay', __name__)
# -------------------------------------------------------------
# 1. ĐỌC CẤU HÌNH TỪ FILE .ENV
# -------------------------------------------------------------
VNP_TMN_CODE = os.getenv("VNP_TMN_CODE")
VNP_HASH_SECRET = os.getenv("VNP_HASH_SECRET")
VNP_PAY_URL = os.getenv("VNP_PAY_URL", "https://sandbox.vnpayment.vn/paymentv2/vpcpay.html")
VNP_RETURN_URL = os.getenv("VNP_RETURN_URL")
# -------------------------------------------------------------
# 2. HÀM HỖ TRỢ MÃ HÓA (HMAC-SHA512)
# -------------------------------------------------------------
def hmac_sha512(key: str, data: str) -> str:
    """Tạo chữ ký bảo mật bảo vệ dữ liệu truyền đi."""
    byte_key = key.encode('utf-8')
    byte_data = data.encode('utf-8')
    return hmac.new(byte_key, byte_data, hashlib.sha512).hexdigest()
# -------------------------------------------------------------
# 3. API TẠO URL THANH TOÁN (CREATE PAYMENT URL)
# -------------------------------------------------------------
@vnpay_bp.post("/create_payment")
def create_payment():
    try:
        # Nhận dữ liệu truyền từ Frontend (ví dụ: JSON body)
        data = request.get_json() or {}
        amount = data.get("amount")        # Số tiền (VND), ví dụ: 50000
        order_id = data.get("order_id")    # Mã đơn hàng duy nhất từ hệ thống của bạn (ví dụ: Bill_123456)
        order_desc = data.get("order_desc", "Thanh toan don hang xem phim")
        if not amount or not order_id:
            return jsonify({"status": "error", "message": "Thiếu thông tin số tiền (amount) hoặc mã đơn hàng (order_id)"}), 400
        # VNPay yêu cầu số tiền nhân với 100 (để tránh số thập phân)
        vnp_amount = int(amount) * 100
        create_date = datetime.now().strftime("%Y%m%d%H%M%S")
        ip_addr = request.remote_addr or "127.0.0.1"
        # Định nghĩa các tham số gửi sang VNPay
        vnpay_params = {
            "vnp_Version": "2.1.0",
            "vnp_Command": "pay",
            "vnp_TmnCode": VNP_TMN_CODE,
            "vnp_Amount": str(vnp_amount),
            "vnp_CreateDate": create_date,
            "vnp_CurrCode": "VND",
            "vnp_IpAddr": ip_addr,
            "vnp_Locale": "vn",
            "vnp_OrderInfo": order_desc,
            "vnp_OrderType": "billpayment",
            "vnp_ReturnUrl": VNP_RETURN_URL,
            "vnp_TxnRef": str(order_id)
        }
        # Bước A: Sắp xếp các tham số theo thứ tự Alphabet của Key
        sorted_params = sorted(vnpay_params.items())
        # Bước B: Mã hóa url (URL encode) các tham số và nối bằng ký tự '&'
        # Sử dụng urllib.parse.quote để chuyển khoảng trắng thành %20 đúng tiêu chuẩn VNPay
        hash_parts = []
        query_parts = []
        for key, val in sorted_params:
            encoded_key = urllib.parse.quote(str(key))
            encoded_val = urllib.parse.quote(str(val))
            hash_parts.append(f"{encoded_key}={encoded_val}")
            query_parts.append(f"{encoded_key}={encoded_val}")
        hash_data = "&".join(hash_parts)
        query_string = "&".join(query_parts)
        # Bước C: Tính chữ ký checksum bảo mật (HMAC-SHA512)
        secure_hash = hmac_sha512(VNP_HASH_SECRET, hash_data)
        # Bước D: Nối chữ ký bảo mật vào Query String để sinh ra URL hoàn chỉnh
        payment_url = f"{VNP_PAY_URL}?{query_string}&vnp_SecureHash={secure_hash}"
        return jsonify({
            "status": "success",
            "payment_url": payment_url
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
# -------------------------------------------------------------
# 4. API NHẬN THÔNG BÁO TỪ VNPAY (IPN URL - DÙNG ĐỂ CẬP NHẬT DB)
# -------------------------------------------------------------
@vnpay_bp.get("/payment_ipn")
def payment_ipn():
    try:
        # VNPay IPN gọi bằng phương thức GET và truyền các param trên URL
        input_data = request.args.to_dict()
        vnp_secure_hash = input_data.get("vnp_SecureHash")
        if not vnp_secure_hash:
            return jsonify({"RspCode": "97", "Message": "Missing secure hash"}), 400
        # Bước A: Loại bỏ vnp_SecureHash và vnp_SecureHashType khỏi dữ liệu để chuẩn bị băm lại đối chiếu
        if "vnp_SecureHash" in input_data:
            del input_data["vnp_SecureHash"]
        if "vnp_SecureHashType" in input_data:
            del input_data["vnp_SecureHashType"]
        # Bước B: Sắp xếp các tham số còn lại theo Alphabet
        sorted_input = sorted(input_data.items())
        # Bước C: Tạo chuỗi băm giống định dạng lúc gửi đi
        hash_parts = []
        for key, val in sorted_input:
            encoded_key = urllib.parse.quote(str(key))
            encoded_val = urllib.parse.quote(str(val))
            hash_parts.append(f"{encoded_key}={encoded_val}")
        hash_data = "&".join(hash_parts)
        # Bước D: Tính toán chữ ký bảo mật dựa trên Secret Key của bạn
        calculated_hash = hmac_sha512(VNP_HASH_SECRET, hash_data)
        # Bước E: So sánh chữ ký của VNPay với chữ ký tự tính toán
        if calculated_hash.lower() != vnp_secure_hash.lower():
            # Chữ ký không khớp -> Có dấu hiệu giả mạo request
            return jsonify({"RspCode": "97", "Message": "Invalid Signature"}), 200
        # Nếu chữ ký khớp, bắt đầu kiểm tra logic nghiệp vụ:
        txn_ref = input_data.get("vnp_TxnRef")       # Mã đơn hàng của bạn
        vnp_amount = input_data.get("vnp_Amount")    # Số tiền VNPay trả về (đã nhân 100)
        response_code = input_data.get("vnp_ResponseCode") # Mã trạng thái giao dịch ("00" là thành công)
        # TODO: Bạn cần viết code để kết nối Database kiểm tra các điều kiện sau:
        # 1. Kiểm tra đơn hàng có tồn tại trong DB không? (Nếu không -> return RspCode: "01", Message: "Order not found")
        # 2. Kiểm tra số tiền gửi đi và số tiền VNPay báo về có khớp không? (Nếu không -> return RspCode: "04", Message: "Invalid Amount")
        # 3. Kiểm tra trạng thái đơn hàng hiện tại trong DB xem đã thanh toán chưa? (Tránh cập nhật đè nếu đã xử lý rồi -> return RspCode: "02", Message: "Order already confirmed")
        
        if response_code == "00":
            # Giao dịch thành công trên VNPay.
            # TODO: Cập nhật trạng thái đơn hàng trong Database của bạn thành "Đã thanh toán"
            print(f"Đơn hàng {txn_ref} thanh toán thành công số tiền {float(vnp_amount)/100} VND")
        else:
            # Giao dịch thất bại
            # TODO: Cập nhật trạng thái đơn hàng thành "Thất bại"
            print(f"Đơn hàng {txn_ref} thanh toán thất bại. Mã lỗi: {response_code}")
        # Trả về phản hồi chuẩn cho VNPay biết hệ thống của bạn đã ghi nhận thông tin
        return jsonify({"RspCode": "00", "Message": "Confirm Success"}), 200
    except Exception as e:
        return jsonify({"RspCode": "99", "Message": f"System Error: {str(e)}"}), 200

from flask import render_template_string

# -------------------------------------------------------------
# 5. API HIỂN THỊ KẾT QUẢ CHO NGƯỜI DÙNG (RETURN URL)
# -------------------------------------------------------------
@vnpay_bp.get("/payment_return")
def payment_return():
    try:
        # Lấy toàn bộ tham số VNPay gửi trả về từ query parameters
        input_data = request.args.to_dict()
        vnp_secure_hash = input_data.get("vnp_SecureHash")

        # Loại bỏ các tham số bảo mật ra khỏi chuỗi tính băm đối chiếu
        if "vnp_SecureHash" in input_data:
            del input_data["vnp_SecureHash"]
        if "vnp_SecureHashType" in input_data:
            del input_data["vnp_SecureHashType"]

        # Sắp xếp các tham số phản hồi theo alphabet
        sorted_input = sorted(input_data.items())

        # Tạo chuỗi băm
        hash_parts = []
        for key, val in sorted_input:
            encoded_key = urllib.parse.quote(str(key))
            encoded_val = urllib.parse.quote(str(val))
            hash_parts.append(f"{encoded_key}={encoded_val}")
        
        hash_data = "&".join(hash_parts)

        # Tính toán chữ ký kiểm tra chéo
        calculated_hash = hmac_sha512(VNP_HASH_SECRET, hash_data)

        # Khởi tạo trạng thái mặc định
        status = "failed"
        message = "Giao dịch thất bại hoặc đã bị hủy"
        txn_ref = input_data.get("vnp_TxnRef", "N/A")
        amount_raw = input_data.get("vnp_Amount", "0")
        amount = float(amount_raw) / 100 if amount_raw.isdigit() else 0

        # Kiểm tra chữ ký khớp và kiểm tra mã trạng thái
        if calculated_hash.lower() == vnp_secure_hash.lower():
            response_code = input_data.get("vnp_ResponseCode")
            if response_code == "00":
                status = "success"
                message = "Thanh toán thành công!"
            else:
                message = f"Giao dịch không thành công (Mã lỗi: {response_code})"
        else:
            message = "Chữ ký bảo mật không hợp lệ (Dữ liệu bị sửa đổi)"

        # Render giao diện HTML Dark-Mode cao cấp giống phong cách của app
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Kết quả thanh toán</title>
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <style>
                body {{
                    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
                    text-align: center;
                    padding: 80px 20px;
                    background-color: #121212;
                    color: #ffffff;
                    margin: 0;
                }}
                .card {{
                    background: #1e1e1e;
                    padding: 40px 30px;
                    border-radius: 16px;
                    max-width: 420px;
                    margin: 0 auto;
                    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.5);
                    border: 1px solid #2e2e2e;
                }}
                .icon {{
                    font-size: 72px;
                    margin-bottom: 24px;
                }}
                .success {{ color: #4CAF50; }}
                .failed {{ color: #E50914; }}
                h2 {{ margin-top: 0; font-size: 24px; font-weight: 700; }}
                p {{ color: #aaaaaa; font-size: 16px; margin: 8px 0; }}
                .info-box {{
                    background: #2b2b2b;
                    padding: 15px;
                    border-radius: 8px;
                    margin: 20px 0;
                    text-align: left;
                }}
                .info-row {{
                    display: flex;
                    justify-content: space-between;
                    margin: 5px 0;
                }}
                .btn {{
                    display: inline-block;
                    margin-top: 20px;
                    padding: 14px 28px;
                    background: #E50914; /* Netflix Red */
                    color: white;
                    text-decoration: none;
                    border-radius: 8px;
                    font-weight: bold;
                    transition: background 0.2s;
                }}
                .btn:hover {{
                    background: #b20710;
                }}
            </style>
        </head>
        <body>
            <div class="card">
                <div class="icon {'success' if status == 'success' else 'failed'}">
                    {'✓' if status == 'success' else '✕'}
                </div>
                <h2 class="{'success' if status == 'success' else 'failed'}">{message}</h2>
                
                <div class="info-box">
                    <div class="info-row">
                        <span>Mã đơn hàng:</span>
                        <strong>{txn_ref}</strong>
                    </div>
                    <div class="info-row">
                        <span>Số tiền:</span>
                        <strong>{amount:,.0f} VND</strong>
                    </div>
                </div>

                <!-- Deep link quay về app Expo (tkfilm:// là URL Scheme định nghĩa ở app.json) -->
                <a href="tkfilm://payment-result?status={status}&txn_ref={txn_ref}" class="btn">
                    Quay lại ứng dụng
                </a>
            </div>
        </body>
        </html>
        """
        return render_template_string(html_content)

    except Exception as e:
        return f"Có lỗi hệ thống xảy ra: {str(e)}", 500
