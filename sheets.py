"""
IXTIYORIY: Buyurtmalarni Google Sheets jadvaliga avtomatik yozib boradi.
Sozlanmagan bo'lsa, bot xatolik bermaydi — shunchaki bu funksiya ishlamaydi
va buyurtma faqat sizga Telegram xabari sifatida keladi.

Sozlash uchun README.md faylidagi "Google Sheets ulash" bo'limiga qarang.
"""
import json
import os


def append_order_to_sheet(order: dict):
    sheet_id = os.getenv("GOOGLE_SHEET_ID")
    creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
    if not sheet_id or not creds_json:
        raise RuntimeError("Google Sheets sozlanmagan (GOOGLE_SHEET_ID yoki GOOGLE_CREDENTIALS_JSON yo'q)")

    import gspread
    from google.oauth2.service_account import Credentials

    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds_dict = json.loads(creds_json)
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(sheet_id)
    ws = sh.sheet1

    items_str = "; ".join(f"{i['name']} x{i['qty']}" for i in order["items"])
    customer = order.get("customer", {})
    ws.append_row([
        customer.get("name", ""),
        customer.get("phone", ""),
        customer.get("address", ""),
        items_str,
        order.get("payment", ""),
        order.get("total", 0),
    ])
