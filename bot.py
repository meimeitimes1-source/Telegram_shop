from pathlib import Path

path = Path("bot.py")
text = path.read_text(encoding="utf-8")

if '"/api/orders"' in text or "'/api/orders'" in text:
    print("APK API allaqachon mavjud — o'zgartirish kiritilmadi.")
    raise SystemExit

marker = "\nasync def start_web_server():"
if marker not in text:
    raise SystemExit("start_web_server() topilmadi.")

api_code = r"""
async def create_app_order_api(request: web.Request):
    """Create an order from the standalone Android APK."""
    cors = {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Headers": "Content-Type",
        "Access-Control-Allow-Methods": "POST,OPTIONS",
    }

    if request.method == "OPTIONS":
        return web.Response(status=204, headers=cors)

    try:
        data = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "JSON noto'g'ri"},
                                  status=400, headers=cors)

    try:
        user_id = int(data.get("user_id", 0))
    except (TypeError, ValueError):
        user_id = 0

    if not user_id:
        return web.json_response({"ok": False, "error": "user_id kerak"},
                                  status=400, headers=cors)

    try:
        items = data.get("items", [])
        if not items:
            raise ValueError("Savat bo'sh.")

        customer = data.get("customer", {})
        payment = data.get("payment", "naqd")
        delivery = int(data.get("delivery", 0) or 0)
        total = int(data.get("total", 0) or 0)

        order_id = uuid.uuid4().hex[:8].upper()
        payment_status = "cash_on_delivery" if payment == "naqd" else "pending"

        order_record = {
            "order_id": order_id,
            "status": "accepted",
            "source": "android_apk",
            "user_id": user_id,
            "username": data.get("username"),
            "customer": customer,
            "items": items,
            "payment": payment,
            "payment_status": payment_status,
            "delivery": delivery,
            "total": total,
        }

        save_order(order_record)

        if ADMIN_ID:
            lines = [
                "📱 <b>APKdan yangi buyurtma</b>",
                f"👤 Mijoz: {customer.get('name', '-')}",
                f"📞 Telefon: {customer.get('phone', '-')}",
                f"📍 Manzil: {customer.get('address', '-')}",
                f"💳 To'lov: {payment_label(payment)}",
                "",
                "🛒 Mahsulotlar:",
            ]
            for item in items:
                qty = int(item.get("qty", 0))
                price = int(item.get("price", 0))
                lines.append(
                    f"• {item.get('name', '-')} x{qty} — {price * qty:,} so'm"
                )
            lines += [
                "",
                f"💰 <b>Jami: {total:,} so'm</b>",
                f"🆔 <b>Buyurtma: #{order_id}</b>",
                f"💳 Holat: {payment_status_label(payment_status)}",
            ]
            await bot.send_message(ADMIN_ID, "\n".join(lines))

        return web.json_response(
            {"ok": True, "order_id": order_id, "payment_status": payment_status},
            headers=cors,
        )

    except ValueError as e:
        return web.json_response({"ok": False, "error": str(e)},
                                  status=400, headers=cors)
    except Exception:
        logging.exception("APK buyurtmasini yaratishda xato")
        return web.json_response({"ok": False, "error": "Server xatosi"},
                                  status=500, headers=cors)

"""

text = text.replace(marker, api_code + marker, 1)

route_marker = 'app.router.add_post("/reviews", create_review_api)'
if route_marker in text:
    text = text.replace(
        route_marker,
        route_marker +
        '\n    app.router.add_post("/api/orders", create_app_order_api)' +
        '\n    app.router.add_options("/api/orders", create_app_order_api)',
        1
    )
else:
    app_marker = "app = web.Application()"
    if app_marker not in text:
        raise SystemExit("web server route joyi topilmadi.")
    text = text.replace(
        app_marker,
        app_marker +
        '\n    app.router.add_post("/api/orders", create_app_order_api)' +
        '\n    app.router.add_options("/api/orders", create_app_order_api)',
        1
    )

out = Path("bot_patched_for_apk.py")
out.write_text(text, encoding="utf-8")
print(f"Tayyor: {out}")
print("Asl bot.py o'zgartirilmadi.")
