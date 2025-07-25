import os
import logging
import tempfile
from types import SimpleNamespace
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)
from enkanetwork import EnkaNetworkAPI
from enkacard.encbanner import ENC
# === CONFIG ===
BOT_TOKEN = "7436385410:AAFtdUT_Ewmg4YHnB7yrT174ZMTRCpy7xH8"
user_uid_map = {}
user_cache = {}
user_template_settings = {}  # ✅ NEW

# === Logging ===
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s"
)
logger = logging.getLogger(__name__)


# === PATCH ICON FALLBACKS ===
def patch_enka_user(player):
    if not player:
        return

    logger.debug("Patching user icons...")
    if getattr(player, "avatar", None) is None:
        player.avatar = SimpleNamespace(icon=SimpleNamespace(
            filename="UI_AvatarIcon_PlayerBoy",
            url="https://enka.network/ui/UI_AvatarIcon_PlayerBoy.png"
        ))
    else:
        icon_obj = getattr(player.avatar, "icon", None)
        if icon_obj is None:
            player.avatar.icon = SimpleNamespace(
                filename="UI_AvatarIcon_PlayerBoy",
                url="https://enka.network/ui/UI_AvatarIcon_PlayerBoy.png"
            )
        elif getattr(icon_obj, "filename", None):
            player.avatar.icon.url = f"https://enka.network/ui/{icon_obj.filename}.png"

    for char in getattr(player, "characters", []):
        icon_obj = getattr(char, "icon", None)
        if icon_obj and getattr(icon_obj, "filename", None):
            icon_obj.url = f"https://enka.network/ui/{icon_obj.filename}.png"


# === /start ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Welcome! Use /myc to view your Genshin Impact profile.")


# === /myc ===
async def myc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_uid_map:
        await update.message.reply_text("🔢 Please send your Genshin UID.")
        context.user_data["awaiting_uid"] = True
        return
    uid = user_uid_map[user_id]
    await generate_profile_card(update, context, uid)


# === UID input handler ===
async def handle_uid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("awaiting_uid"):
        return
    uid_text = update.message.text.strip()
    if not uid_text.isdigit():
        await update.message.reply_text("❌ Invalid UID. Use digits only.")
        return
    user_uid_map[update.effective_user.id] = uid_text
    context.user_data["awaiting_uid"] = False
    await update.message.reply_text(f"✅ UID set to {uid_text}. Fetching your profile...")
    await generate_profile_card(update, context, uid_text)

# === /template ===
async def template_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📄 Profile Template", callback_data="choose_profile_template")],
        [InlineKeyboardButton("🃏 Card Template", callback_data="choose_card_template")]
    ])
    await update.message.reply_text("⚙️ Choose what to customize:", reply_markup=keyboard)


# === Profile Template Selector ===
async def profile_template_selector(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🧩 Profile Template 1", callback_data="profile_template_1")],
        [InlineKeyboardButton("🧩 Profile Template 2", callback_data="profile_template_2")]
    ])
    await update.callback_query.answer()
    await update.callback_query.message.reply_text("📄 Choose a profile template:", reply_markup=keyboard)


# === Card Template Selector ===
async def card_template_selector(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🃏 Card Template {i}", callback_data=f"card_template_{i}")]
        for i in range(1, 6)
    ])
    await update.callback_query.answer()
    await update.callback_query.message.reply_text("🃏 Choose a card template:", reply_markup=keyboard)


# === Store Template Choice ===
async def store_template_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    parts = query.data.split("_")
    category = parts[0]  # 'profile' or 'card'
    template_num = int(parts[-1])

    if user_id not in user_template_settings:
        user_template_settings[user_id] = {}

    user_template_settings[user_id][category] = template_num
    await query.message.reply_text(f"✅ {category.capitalize()} template set to {template_num}!")

# === Generate profile overview + buttons ===
async def generate_profile_card(update: Update, context: ContextTypes.DEFAULT_TYPE, uid: str):
    message = await update.message.reply_text("⏳ Fetching profile from Enka.Network...")
    logger.info(f"Fetching Enka profile for UID: {uid}")

    try:
        async with EnkaNetworkAPI() as client:
            await client.set_language("en")
            user = await client.fetch_user_by_uid(int(uid))

        if not user.characters:
            await message.edit_text("⚠️ No public characters found or profile is private.")
            return

        logger.info("Profile fetched. Patching player info...")
        patch_enka_user(user.player)
        user_cache[update.effective_user.id] = user
        await message.edit_text("🖼 Generating profile card...")
        logger.info("Calling encard.profile...")

        # ✅ Fetch user profile template setting (default to 1)
        template_profile = user_template_settings.get(update.effective_user.id, {}).get("profile", 1)

        async with ENC(uid=uid, lang="en") as encard:
            profile = await encard.profile(card=True, teamplate=template_profile)
            logger.info(f"profile type: {type(profile)}, dir: {dir(profile)}")
            logger.info(f"profile.card type: {type(profile.card)}")
            logger.info("Profile card generated.")

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            image_path = tmp.name
            profile.card.save(image_path)
            logger.info(f"Profile image saved: {image_path}")

        keyboard = []
        row = []
        for idx, char in enumerate(user.characters[:12]):
            button = InlineKeyboardButton(char.name, callback_data=f"char_{char.id}")
            row.append(button)
            if (idx + 1) % 4 == 0:
                keyboard.append(row)
                row = []

        if row:
            keyboard.append(row)

        reply_markup = InlineKeyboardMarkup(keyboard)

        with open(image_path, "rb") as f:
            await update.message.reply_photo(f, caption=f"📋 UID {uid} Profile", reply_markup=reply_markup)

        os.remove(image_path)
        logger.info("Profile card sent and temp file removed.")

    except Exception as e:
        logger.exception("Card generation error")
        await message.edit_text(f"🚫 Failed to fetch profile:\n{e}")

# === Character Build Handler ===
async def character_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    uid = user_uid_map.get(user_id)

    if not uid:
        return await query.message.reply_text("❌ UID not found. Please run /myc again.")

    try:
        logger.info(f"Generating character build for UID: {uid}")
        await query.message.reply_text("🧱 Generating character build...")

        # ✅ Fetch user card template setting (default to 1)
        template_card = user_template_settings.get(user_id, {}).get("card", 1)

        async with ENC(uid=uid, lang="en") as encard:
            result = await encard.creat(template=template_card)
            logger.info("Builds generated.")

        char_id_from_button = int(query.data.split("_")[1])
        logger.debug(f"Looking for character ID: {char_id_from_button}")

        found = False
        for card_obj in result.card:
            if card_obj.id != char_id_from_button:
                continue

            found = True
            char_name = card_obj.name
            img = card_obj.card

            if img is None:
                logger.warning(f"No image found for character ID {char_id_from_button}")
                return await query.message.reply_text("⚠️ No image found for character.")

            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                image_path = tmp.name
                img.save(image_path)
                logger.info(f"Build image saved for {char_name}: {image_path}")

            with open(image_path, "rb") as f:
                await query.message.reply_photo(f, caption=f"🔧 Build: {char_name}")

            os.remove(image_path)
            logger.info("Character build image sent and temp file removed.")
            break

        if not found:
            logger.warning("Character not found in builds.")
            await query.message.reply_text("⚠️ Character not found in your Enka profile.")

    except Exception as e:
        logger.exception("Character build error")
        await query.message.reply_text("🚫 Failed to generate character build.")

# === Run Bot ===
if __name__ == "__main__":
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("myc", myc))
    app.add_handler(CommandHandler("template", template_menu))  # ✅ NEW
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_uid))
    app.add_handler(CallbackQueryHandler(character_callback, pattern=r"^char_\d+$"))
    app.add_handler(CallbackQueryHandler(profile_template_selector, pattern="^choose_profile_template$"))  # ✅
    app.add_handler(CallbackQueryHandler(card_template_selector, pattern="^choose_card_template$"))  # ✅
    app.add_handler(CallbackQueryHandler(store_template_choice, pattern="^(profile|card)_template_\d+$"))  # ✅

    logger.info("🚀 Bot is running...")
    app.run_polling()
#Credits to @TheLastSkywalker
