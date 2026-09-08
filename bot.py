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
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)

dp = Dispatcher()
router = Router()
dp.include_router(router)

pending_photo_product = {}


def load_products():
    if not PRODUCTS_FILE.exists():
        return []

    try:
        with open(PRODUCTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        logging.exception("products.json o'qilmadi")
        return []


def save_products(products):
    with open(PRODUCTS_FILE, "w", encoding="utf-8") as f:
        json.dump(products, f, ensure_ascii=False, indent=2)


def save_order(order):
    orders = []

    if ORDERS_FILE.exists():
        try:
            with open(ORDERS_FILE, "r", encoding="utf-8") as f:
                orders = json.load(f)
        except (json.JSONDecodeError, OSError):
            orders = []

    orders.append(order)

    with open(ORDERS_FILE, "w", encoding="utf-8") as f:
        json.dump(orders, f, ensure_ascii=False, indent=2)

    try:
        from sheets import append_order_to_sheet
        append_order_to_sheet(order)
    except Exception as e:
        logging.warning(
            "Google Sheets'ga yozilmadi (ixtiyoriy): %s",
            e,
        )


def is_admin(user_id: int) -> bool:
    return ADMIN_ID != 0 and user_id == ADMIN_ID


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
            f"https://checkout.paycom.uz/{merchant_id}"
            f"?amount={amount_tiyin}"
            f"&account[user_id]={user_id}"
        )

    if payment == "click":
        merchant_id = os.getenv("CLICK_MERCHANT_ID", "")

        if not merchant_id:
            return "⚠️ Click hali ulanmagan. Admin bilan bog'laning."

        return (
            "https://my.click.uz/services/pay"
            f"?service_id={merchant_id}"
            f"&amount={amount}"
            f"&transaction_param={user_id}"
        )

    return ""


@router.message(Command("start"))
async def cmd_start(message: Message):
    if not WEBAPP_URL:
        await message.answer(
            "Do'kon hali sozlanmagan. "
            "Admin WEBAPP_URL manzilini kiritishi kerak."
        )
        return

    kb = ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(
                    text="🛍 Do'konni ochish",
                    web_app=WebAppInfo(url=WEBAPP_URL),
                )
            ]
        ],
        resize_keyboard=True,
    )

    await message.answer(
        "Assalomu alaykum! 👋\n\n"
        "Bizning onlayn do'konimizga xush kelibsiz.\n"
        "Mahsulotlarni ko'rish va buyurtma berish uchun "
        "quyidagi tugmani bosing.",
        reply_markup=kb,
    )


@router.message(F.web_app_data)
async def handle_webapp_order(message: Message):
    try:
        data = json.loads(message.web_app_data.data)
    except (json.JSONDecodeError, AttributeError):
        await message.answer(
            "Buyurtmada xatolik yuz berdi, qaytadan urinib ko'ring."
        )
        return

    items = data.get("items", [])
    customer = data.get("customer", {})
    payment = data.get("payment", "naqd")
    total = data.get("total", 0)

    if not items:
        await message.answer("Savat bo'sh.")
        return

    lines = [
        "🆕 <b>Yangi buyurtma</b>\n",
        f"👤 Mijoz: {customer.get('name', '-')}",
        f"📞 Telefon: {customer.get('phone', '-')}",
        f"📍 Manzil: {customer.get('address', '-')}",
        f"💳 To'lov turi: {payment_label(payment)}\n",
        "🛒 Mahsulotlar:",
    ]

    for item in items:
        lines.append(
            f"  • {item['name']} x{item['qty']} — "
            f"{item['price'] * item['qty']:,} so'm"
        )

    lines.append(f"\n💰 <b>Jami: {total:,} so'm</b>")

    lines.append(
        f"\n🆔 Buyurtmachi: "
        f"<a href='tg://user?id={message.from_user.id}'>"
        f"{message.from_user.full_name}</a>"
    )

    order_text = "\n".join(lines)

    order_record = {
        "user_id": message.from_user.id,
        "username": message.from_user.username,
        "customer": customer,
        "items": items,
        "payment": payment,
        "total": total,
    }

    save_order(order_record)

    if ADMIN_ID:
        await bot.send_message(ADMIN_ID, order_text)

    if payment == "naqd":
        await message.answer(
            "✅ Buyurtmangiz qabul qilindi!\n"
            "Tez orada siz bilan bog'lanamiz.\n"
            "To'lov: yetkazib berishda naqd."
        )
    else:
        link = payment_link(
            payment,
            int(total),
            message.from_user.id,
        )

        await message.answer(
            "✅ Buyurtmangiz qabul qilindi!\n\n"
            f"To'lov uchun havola:\n{link}\n\n"
            "To'lovdan so'ng buyurtmangiz tasdiqlanadi."
        )


@router.message(Command("mahsulotlar"))
async def cmd_list_products(message: Message):
    if not is_admin(message.from_user.id):
        return

    products = load_products()

    if not products:
        await message.answer(
            "Hozircha mahsulot yo'q. "
            "/qoshish buyrug'i bilan qo'shing."
        )
        return

    lines = []

    for p in products:
        status = (
            "🖼 rasm bor"
            if p.get("photo_file_id")
            else "📷 rasm yo'q"
        )

        lines.append(
            f"#{p['id']} — {p['name']} — "
            f"{p['price']:,} so'm "
            f"({p.get('category', '-')}) — {status}"
        )

    await message.answer("\n".join(lines))


@router.message(Command("qoshish"))
async def cmd_add_product(
    message: Message,
    command: CommandObject,
):
    if not is_admin(message.from_user.id):
        return

    if not command.args:
        await message.answer(
            "Format:\n"
            "/qoshish Nomi | Narxi | Tavsif | "
            "Rasm-havolasi | Turkum\n\n"
            "Masalan:\n"
            "/qoshish Krossovka | 450000 | "
            "Qora, 42-razmer | "
            "https://example.com/rasm.jpg | "
            "Poyabzal"
        )
        return

    parts = [
        p.strip()
        for p in command.args.split("|")
    ]

    if len(parts) < 4:
        await message.answer(
            "Kamida: Nomi | Narxi | Tavsif | "
            "Rasm-havolasi kiriting."
        )
        return

    name, price_str, desc, photo = parts[:4]

    category = (
        parts[4]
        if len(parts) > 4
        else "Umumiy"
    )

    try:
        price = int(
            price_str
            .replace(" ", "")
            .replace(",", "")
        )
    except ValueError:
        await message.answer(
            "Narxni faqat raqamda kiriting. "
            "Masalan: 450000"
        )
        return

    products = load_products()

    new_id = max(
        (p["id"] for p in products),
        default=0,
    ) + 1

    products.append(
        {
            "id": new_id,
            "name": name,
            "price": price,
            "desc": desc,
            "photo": photo,
            "category": category,
        }
    )

    save_products(products)

    await message.answer(
        f"✅ Qo'shildi: #{new_id} "
        f"{name} — {price:,} so'm\n\n"
        f"Rasm qo'yish uchun:\n"
        f"/rasm {new_id}"
    )


@router.message(Command("rasm"))
async def cmd_set_photo(
    message: Message,
    command: CommandObject,
):
    if not is_admin(message.from_user.id):
        return

    if (
        not command.args
        or not command.args.strip().isdigit()
    ):
        await message.answer(
            "Format: /rasm <mahsulot_id>\n"
            "Masalan: /rasm 1\n\n"
            "Keyin mahsulot rasmini shu chatga yuboring."
        )
        return

    product_id = int(
        command.args.strip()
    )

    products = load_products()

    product = next(
        (
            p
            for p in products
            if p["id"] == product_id
        ),
        None,
    )

    if not product:
        await message.answer(
            f"❌ #{product_id} mahsulot topilmadi."
        )
        return

    pending_photo_product[
        message.from_user.id
    ] = product_id

    await message.answer(
        f"📸 #{product_id} — {product['name']}\n\n"
        "Endi shu mahsulot rasmini yuboring.\n"
        "Rasm kelishi bilan avtomatik saqlanadi."
    )


@router.message(F.photo)
async def receive_product_photo(message: Message):
    if not is_admin(message.from_user.id):
        return

    product_id = pending_photo_product.get(
        message.from_user.id
    )

    if not product_id:
        return

    photo = message.photo[-1]
    file_id = photo.file_id

    products = load_products()

    product = next(
        (
            p
            for p in products
            if p["id"] == product_id
        ),
        None,
    )

    if not product:
        pending_photo_product.pop(
            message.from_user.id,
            None,
        )

        await message.answer(
            f"❌ #{product_id} mahsulot topilmadi."
        )
        return

    product["photo_file_id"] = file_id

    save_products(products)

    pending_photo_product.pop(
        message.from_user.id,
        None,
    )

    await message.answer(
        "✅ Rasm saqlandi!\n\n"
        f"Mahsulot: #{product_id} — "
        f"{product['name']}\n"
        "Mini App'da mahsulot rasmi Telegram orqali "
        "ko'rsatiladi."
    )


@router.message(Command("ochirish"))
async def cmd_delete_product(
    message: Message,
    command: CommandObject,
):
    if not is_admin(message.from_user.id):
        return

    if (
        not command.args
        or not command.args.strip().isdigit()
    ):
        await message.answer(
            "Format: /ochirish <id>\n"
            "Masalan: /ochirish 3"
        )
        return

    pid = int(
        command.args.strip()
    )

    products = load_products()

    new_products = [
        p
        for p in products
        if p["id"] != pid
    ]

    if len(new_products) == len(products):
        await message.answer(
            f"#{pid} topilmadi."
        )
        return

    save_products(new_products)

    await message.answer(
        f"🗑 #{pid} o'chirildi."
    )


@router.message(Command("yordam"))
async def cmd_help(message: Message):
    if not is_admin(message.from_user.id):
        return

    await message.answer(
        "Admin buyruqlari:\n\n"
        "/qoshish Nomi | Narxi | Tavsif | "
        "Rasm-havolasi | Turkum — mahsulot qo'shish\n"
        "/mahsulotlar — mahsulotlar ro'yxati\n"
        "/rasm <id> — mahsulotga Telegram rasmi qo'yish\n"
        "/ochirish <id> — mahsulotni o'chirish"
    )


async def get_products_api(request):
    return web.json_response(
        load_products(),
        headers={
            "Access-Control-Allow-Origin": "*"
        },
    )


async def get_telegram_photo(request):
    file_id = request.match_info.get(
        "file_id"
    )

    if not file_id:
        return web.Response(
            status=400,
            text="file_id kerak",
        )

    try:
        file = await bot.get_file(
            file_id
        )

        if not file.file_path:
            return web.Response(
                status=404,
                text="Telegram fayli topilmadi",
            )

        file_url = (
            f"https://api.telegram.org/file/bot"
            f"{BOT_TOKEN}/{file.file_path}"
        )

        async with ClientSession() as session:
            async with session.get(
                file_url
            ) as response:

                if response.status != 200:
                    return web.Response(
                        status=response.status,
                        text="Telegramdan rasmni olishda xatolik",
                    )

                data = await response.read()

                content_type = response.headers.get(
                    "Content-Type",
                    "image/jpeg",
                )

        return web.Response(
            body=data,
            headers={
                "Content-Type": content_type,
                "Cache-Control": "public, max-age=86400",
                "Access-Control-Allow-Origin": "*",
            },
        )

    except Exception:
        logging.exception(
            "Telegram rasmi yuklanmadi: %s",
            file_id,
        )

        return web.Response(
            status=500,
            text="Rasmni yuklashda xatolik",
        )


async def start_web_server():
    app = web.Application()

    app.router.add_get(
        "/products",
        get_products_api,
    )

    app.router.add_get(
        "/photo/{file_id}",
        get_telegram_photo,
    )

    runner = web.AppRunner(app)

    await runner.setup()

    site = web.TCPSite(
        runner,
        "0.0.0.0",
        PORT,
    )

    await site.start()

    logging.info(
        "API ishga tushdi: port=%s, "
        "/products, /photo/{file_id}",
        PORT,
    )


async def main():
    await start_web_server()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
