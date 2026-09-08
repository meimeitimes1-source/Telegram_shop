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
from aiogram.types import Message, WebAppInfo, KeyboardButton, ReplyKeyboardMarkup
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

# Admin mahsulot qo'shish jarayoni uchun vaqtinchalik holat
add_states = {}


# ---------- JSON ----------

def load_products():
    if not PRODUCTS_FILE.exists():
        return []

    try:
        with open(PRODUCTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logging.error(f"products.json o'qilmadi: {e}")
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
            f"https://my.click.uz/services/pay"
            f"?service_id={merchant_id}"
            f"&amount={amount}"
            f"&transaction_param={user_id}"
        )

    return ""


# ---------- START ----------

@router.message(Command("start"))
async def cmd_start(message: Message):
    if not WEBAPP_URL:
        await message.answer(
            "Do'kon hali sozlanmagan. "
            "Admin WEBAPP_URL manzilini Railway Variables'da kiritishi kerak."
        )
        return

    kb = ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(
                    text="🛍 Do'konni ochish",
                    web_app=WebAppInfo(url=WEBAPP_URL)
                )
            ]
        ],
        resize_keyboard=True,
    )

    await message.answer(
        "Assalomu alaykum! 👋\n\n"
        "🛍 <b>Mei Mei Times</b> onlayn do'koniga xush kelibsiz.\n"
        "Mahsulotlarni ko'rish va buyurtma berish uchun "
        "quyidagi tugmani bosing.",
        reply_markup=kb,
    )


# ---------- BUYURTMALAR ----------

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

    lines = ["🆕 <b>Yangi buyurtma</b>\n"]
    lines.append(f"👤 Mijoz: {customer.get('name', '-')}")
    lines.append(f"📞 Telefon: {customer.get('phone', '-')}")
    lines.append(f"📍 Manzil: {customer.get('address', '-')}")
    lines.append(f"💳 To'lov: {payment_label(payment)}\n")
    lines.append("🛒 Mahsulotlar:")

    for item in items:
        price = int(item.get("price", 0))
        qty = int(item.get("qty", 0))
        name = item.get("name", "-")

        lines.append(
            f"  • {name} x{qty} — {price * qty:,} so'm"
        )

    lines.append(f"\n💰 <b>Jami: {int(total):,} so'm</b>")
    lines.append(
        f"\n🆔 Buyurtmachi: "
        f"<a href='tg://user?id={message.from_user.id}'>"
        f"{message.from_user.full_name}</a>"
    )

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
        await bot.send_message(
            ADMIN_ID,
            "\n".join(lines)
        )

    if payment == "naqd":
        await message.answer(
            "✅ <b>Buyurtmangiz qabul qilindi!</b>\n\n"
            "Tez orada siz bilan bog'lanamiz.\n"
            "To'lov: yetkazib berishda naqd."
        )
    else:
        link = payment_link(
            payment,
            int(total),
            message.from_user.id
        )

        await message.answer(
            "✅ <b>Buyurtmangiz qabul qilindi!</b>\n\n"
            f"To'lov uchun havola:\n{link}\n\n"
            "To'lovdan so'ng buyurtmangiz tasdiqlanadi."
        )


# ---------- ADMIN: MAHSULOT QO'SHISH ----------

@router.message(Command("qoshish"))
async def cmd_add_product(message: Message, command: CommandObject):
    if not is_admin(message.from_user.id):
        return

    # Eski format ham ishlaydi:
    # /qoshish Nomi | Narxi | Tavsif | Rasm-havolasi | Turkum
    if command.args:
        parts = [p.strip() for p in command.args.split("|")]

        if len(parts) >= 4:
            name = parts[0]
            price_str = parts[1]
            desc = parts[2]
            photo = parts[3]
            category = parts[4] if len(parts) > 4 else "Umumiy"

            try:
                price = int(
                    price_str.replace(" ", "").replace(",", "")
                )
            except ValueError:
                await message.answer(
                    "❌ Narxni faqat raqamda kiriting. Masalan: 30000"
                )
                return

            products = load_products()

            new_id = max(
                (int(p.get("id", 0)) for p in products),
                default=0
            ) + 1

            products.append({
                "id": new_id,
                "name": name,
                "price": price,
                "desc": desc,
                "description": desc,
                "photo": photo,
                "category": category,
            })

            save_products(products)

            await message.answer(
                f"✅ Qo'shildi: #{new_id}\n"
                f"🛍 {name}\n"
                f"💰 {price:,} so'm\n"
                f"📂 {category}"
            )
            return

    # Yangi qulay usul
    add_states[message.from_user.id] = {
        "step": "photo"
    }

    await message.answer(
        "📸 <b>1/7 — Mahsulot rasmini yuboring.</b>\n\n"
        "Rasmni oddiy Telegram orqali yuboring."
    )


@router.message(F.photo)
async def receive_product_photo(message: Message):
    user_id = message.from_user.id

    if not is_admin(user_id):
        return

    state = add_states.get(user_id)

    if not state or state.get("step") != "photo":
        return

    # Eng katta mavjud rasm
    photo = message.photo[-1]

    state["photo"] = photo.file_id
    state["step"] = "name"

    await message.answer(
        "✅ Rasm qabul qilindi.\n\n"
        "✏️ <b>2/7 — Mahsulot nomini yozing.</b>\n\n"
        "Masalan: Erkaklar polarizatsiyalangan ko'zoynagi"
    )


@router.message(F.text)
async def product_add_steps(message: Message):
    user_id = message.from_user.id

    if not is_admin(user_id):
        return

    state = add_states.get(user_id)

    if not state:
        return

    # Buyruqlarni bu handlerda qayta ishlamaymiz
    if message.text.startswith("/"):
        return

    text = message.text.strip()
    step = state.get("step")

    if step == "name":
        state["name"] = text
        state["step"] = "price"

        await message.answer(
            "💰 <b>3/7 — Narxini yozing.</b>\n\n"
            "Masalan: <code>30000</code>",
            parse_mode=ParseMode.HTML
        )
        return

    if step == "price":
        try:
            price = int(
                text.replace(" ", "").replace(",", "")
            )
        except ValueError:
            await message.answer(
                "❌ Narx noto'g'ri.\n"
                "Faqat raqam yozing. Masalan: 30000"
            )
            return

        state["price"] = price
        state["step"] = "description"

        await message.answer(
            "📝 <b>4/7 — Mahsulot tavsifini yozing.</b>\n\n"
            "Masalan: Polarizatsiyalangan linza, "
            "UV himoya va mustahkam karkas."
        )
        return

    if step == "description":
        state["description"] = text
        state["step"] = "category"

        await message.answer(
            "📂 <b>5/7 — Kategoriyasini yozing.</b>\n\n"
            "Masalan: Aksessuarlar"
        )
        return

    if step == "category":
        state["category"] = text
        state["step"] = "old_price"

        await message.answer(
            "🏷 <b>6/7 — Eski narxini yozing.</b>\n\n"
            "Agar chegirma bo'lmasa, <code>0</code> yozing.\n\n"
            "Masalan: <code>45000</code>"
        )
        return

    if step == "old_price":
        try:
            old_price = int(
                text.replace(" ", "").replace(",", "")
            )
        except ValueError:
            await message.answer(
                "❌ Eski narxni raqamda yozing. "
                "Chegirma bo'lmasa 0 yozing."
            )
            return

        state["old_price"] = old_price
        state["step"] = "finish"

        await message.answer(
            "⭐ <b>7/7 — Reytingni yozing.</b>\n\n"
            "Masalan: <code>4.8</code>\n"
            "Agar hozircha reyting bo'lmasa: <code>0</code>"
        )
        return

    if step == "finish":
        try:
            rating = float(text.replace(",", "."))
        except ValueError:
            await message.answer(
                "❌ Reyting masalan <code>4.8</code> ko'rinishida bo'lsin.",
                parse_mode=ParseMode.HTML
            )
            return

        products = load_products()

        new_id = max(
            (int(p.get("id", 0)) for p in products),
            default=0
        ) + 1

        product = {
            "id": new_id,
            "name": state["name"],
            "price": state["price"],
            "old_price": state["old_price"],
            "rating": rating if rating > 0 else None,
            "desc": state["description"],
            "description": state["description"],
            "category": state["category"],

            # Telegram file_id saqlanadi.
            # API frontendga /photo/... URL beradi.
            "photo": state["photo"],
        }

        products.append(product)
        save_products(products)

        add_states.pop(user_id, None)

        old_text = (
            f"\n🏷 Eski narx: {product['old_price']:,} so'm"
            if product["old_price"] > 0
            else ""
        )

        rating_text = (
            f"\n⭐ Reyting: {product['rating']}"
            if product["rating"]
            else ""
        )

        await message.answer(
            "✅ <b>Mahsulot muvaffaqiyatli qo'shildi!</b>\n\n"
            f"🆔 ID: #{new_id}\n"
            f"🛍 {product['name']}\n"
            f"💰 Narx: {product['price']:,} so'm"
            f"{old_text}\n"
            f"📂 Kategoriya: {product['category']}"
            f"{rating_text}"
        )


# ---------- ADMIN: RO'YXAT ----------

@router.message(Command("mahsulotlar"))
async def cmd_list_products(message: Message):
    if not is_admin(message.from_user.id):
        return

    products = load_products()

    if not products:
        await message.answer(
            "📦 Hozircha mahsulot yo'q.\n"
            "/qoshish bilan qo'shing."
        )
        return

    lines = ["📦 <b>Mahsulotlar</b>\n"]

    for p in products:
        lines.append(
            f"#{p.get('id')} — {p.get('name', '-')}\n"
            f"💰 {int(p.get('price', 0)):,} so'm\n"
            f"📂 {p.get('category', '-')}\n"
        )

    await message.answer("\n".join(lines))


# ---------- ADMIN: O'CHIRISH ----------

@router.message(Command("ochirish"))
async def cmd_delete_product(
    message: Message,
    command: CommandObject
):
    if not is_admin(message.from_user.id):
        return

    if not command.args or not command.args.strip().isdigit():
        await message.answer(
            "Format: /ochirish <id>\n"
            "Masalan: /ochirish 3"
        )
        return

    pid = int(command.args.strip())
    products = load_products()

    new_products = [
        p for p in products
        if int(p.get("id", 0)) != pid
    ]

    if len(new_products) == len(products):
        await message.answer(f"❌ #{pid} topilmadi.")
        return

    save_products(new_products)

    await message.answer(
        f"🗑 #{pid} o'chirildi."
    )


# ---------- ADMIN: YORDAM ----------

@router.message(Command("yordam"))
async def cmd_help(message: Message):
    if not is_admin(message.from_user.id):
        return

    await message.answer(
        "🛠 <b>Admin buyruqlari</b>\n\n"
        "/qoshish — rasm yuborib mahsulot qo'shish\n"
        "/mahsulotlar — mahsulotlar ro'yxati\n"
        "/ochirish ID — mahsulotni o'chirish\n"
        "/yordam — yordam"
    )


# ---------- API ----------

async def get_products_api(request):
    products = load_products()

    result = []

    for p in products:
        item = dict(p)

        # Frontend Telegram file_id ko'rmasligi uchun
        # backend orqali rasm URL beramiz.
        if item.get("photo"):
            item["photo"] = (
                f"{request.scheme}://"
                f"{request.host}/photo/"
                f"{item['photo']}"
            )

        result.append(item)

    return web.json_response(
        result,
        headers={"Access-Control-Allow-Origin": "*"}
    )


async def get_photo_api(request):
    file_id = request.match_info["file_id"]

    try:
        telegram_file = await bot.get_file(file_id)

        if not telegram_file.file_path:
            return web.Response(status=404)

        telegram_url = (
            f"https://api.telegram.org/file/bot"
            f"{BOT_TOKEN}/{telegram_file.file_path}"
        )

        async with ClientSession() as session:
            async with session.get(telegram_url) as response:

                if response.status != 200:
                    return web.Response(status=404)

                data = await response.read()

                content_type = response.headers.get(
                    "Content-Type",
                    "image/jpeg"
                )

                return web.Response(
                    body=data,
                    content_type=content_type,
                    headers={
                        "Cache-Control": "public, max-age=86400"
                    }
                )

    except Exception as e:
        logging.error(f"Rasmni olishda xatolik: {e}")
        return web.Response(status=404)


async def start_web_server():
    app = web.Application()

    app.router.add_get(
        "/products",
        get_products_api
    )

    app.router.add_get(
        "/photo/{file_id}",
        get_photo_api
    )

    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(
        runner,
        "0.0.0.0",
        PORT
    )

    await site.start()

    logging.info(
        f"API ishga tushdi: port={PORT}"
    )


# ---------- MAIN ----------

async def main():
    await start_web_server()

    logging.info("BOT ISHLADI")

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
