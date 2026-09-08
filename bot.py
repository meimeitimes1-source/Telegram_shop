import asyncio
import json
import logging
import os
from pathlib import Path

from aiohttp import web, ClientSession
from aiogram import Bot, Dispatcher, F, Router
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandObject
from aiogram.client.default import DefaultBotProperties
from aiogram.types import (
    Message,
    WebAppInfo,
    KeyboardButton,
    ReplyKeyboardMarkup,
)
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
WEBAPP_URL = os.getenv("WEBAPP_URL")
PORT = int(os.getenv("PORT", "8080"))

BASE_DIR = Path(__file__).parent
PRODUCTS_FILE = BASE_DIR / "products.json"
ORDERS_FILE = BASE_DIR / "orders.json"

logging.basicConfig(level=logging.INFO)

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)

dp = Dispatcher()
router = Router()
dp.include_router(router)

# Admin qaysi mahsulotga rasm yuborayotganini vaqtincha saqlaydi
pending_photo = {}


# =========================
# PRODUCTS
# =========================

def load_products():
    if not PRODUCTS_FILE.exists():
        return []

    try:
        with open(PRODUCTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def save_products(products):
    with open(PRODUCTS_FILE, "w", encoding="utf-8") as f:
        json.dump(products, f, ensure_ascii=False, indent=2)


# =========================
# ORDERS
# =========================

def save_order(order):
    orders = []

    if ORDERS_FILE.exists():
        try:
            with open(ORDERS_FILE, "r", encoding="utf-8") as f:
                orders = json.load(f)
        except Exception:
            orders = []

    orders.append(order)

    with open(ORDERS_FILE, "w", encoding="utf-8") as f:
        json.dump(orders, f, ensure_ascii=False, indent=2)

    try:
        from sheets import append_order_to_sheet
        append_order_to_sheet(order)
    except Exception as e:
        logging.warning(
            f"Google Sheets'ga yozilmadi (ixtiyoriy): {e}"
        )


# =========================
# ADMIN
# =========================

def is_admin(user_id: int) -> bool:
    return ADMIN_ID != 0 and user_id == ADMIN_ID


# =========================
# PAYMENT
# =========================

def payment_label(payment: str) -> str:
    return {
        "naqd": "Naqd (yetkazib berishda)",
        "payme": "Payme",
        "click": "Click",
    }.get(payment, payment)


def payment_link(payment: str, amount: int, user_id: int) -> str:

    if payment == "payme":
        merchant_id = os.getenv("PAYME_MERCHANT_ID", "")

        if not merchant_id:
            return "⚠️ Payme hali ulanmagan. Admin bilan bog'laning."

        amount_tiyin = amount * 100

        return (
            f"https://checkout.paycom.uz/"
            f"{merchant_id}"
            f"?amount={amount_tiyin}"
            f"&account[user_id]={user_id}"
        )

    if payment == "click":
        merchant_id = os.getenv("CLICK_MERCHANT_ID", "")

        if not merchant_id:
            return "⚠️ Click hali ulanmagan. Admin bilan bog'laning."

        return (
            f"https://my.click.uz/services/pay"
            f"?service_id={merchant_id}"
            f"&amount={amount}"
            f"&transaction_param={user_id}"
        )

    return ""


# =========================
# START
# =========================

@router.message(Command("start"))
async def cmd_start(message: Message):

    if not WEBAPP_URL:
        await message.answer(
            "Do'kon hali sozlanmagan. "
            "
