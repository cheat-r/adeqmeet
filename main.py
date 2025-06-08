import logging, asyncio, json, os
from collections import defaultdict
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, InputMediaVideo
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, ContextTypes, filters

CHANNEL = '-1002016542799'
ADMIN = '-1002174615446'

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

media_group_cache = defaultdict(list)
media_group_tasks = {}
media_group_lock = asyncio.Lock()

if os.path.exists('db.json'):
    with open('db.json', 'r', encoding='utf-8') as fp:
        db = json.load(fp)
else:
    db = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not str(update.effective_user.id) in db.keys():
        db[str(update.effective_user.id)] = {
            "msg_id": None,
            "status": 'unpub',
            "ban": False,
            "chat_id": update.message.chat_id
        }
        await context.bot.send_message(chat_id=update.effective_chat.id, text="Приветствуем! Отправьте сюда свою анкету, и в скором времени мы её выложим!\nЕсли захотите удалить анкету, воспользуйтесь командой /delete.")
        with open('db.json', 'w', encoding='utf-8') as fp:
            json.dump(db, fp, indent=2, ensure_ascii=False)

async def help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(chat_id=update.effective_chat.id, text="вам никто не поможет.")

async def unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text('Вы не указали айди пользователя!')
        return
    try:
        member = await context.bot.get_chat_member(ADMIN, update.effective_user.id)
        if member.status in ('kicked', 'left'):
            await update.message.reply_text("Команда доступна только администраторам.")
            return
        try:
            if db[context.args[0]]['ban'] == False:
                await update.message.reply_text('Пользователь не в бане!')
                return
            db[context.args[0]]['ban'] = False
            await update.message.reply_text("Пользователь разбанен.")
            with open('db.json', 'w', encoding='utf-8') as fp:
                json.dump(db, fp, indent=2, ensure_ascii=False)
        except:
            await update.message.reply_text('Пользователя нет в базе данных или вы неправильно указали айди.')
    except:
        await update.message.reply_text(f"Команда доступна только администраторам.")

async def delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if db[str(update.effective_user.id)]['status'] == 'pending' or db[str(update.effective_user.id)]['status'] == 'unpub':
        if not db[str(update.effective_user.id)]['msg_id']:
            await context.bot.send_message(chat_id=update.effective_chat.id, text="Пока что вам нечего удалять...")
        else:
            await context.bot.send_message(chat_id=update.effective_chat.id, text="Админы ещё проверяют вашу новую анкету!\nНе волнуйтесь, старая анкета будет удалена автоматически после одобрения.\nЕсли вашу анкету всё же не одобрят, воспользуйтесь командой ещё раз.")
        return
    keyboard = [
        [InlineKeyboardButton("💥 Да, удалить!", callback_data="delete.accept"), InlineKeyboardButton("🌻 Нет, я передумал", callback_data="delete.cancel")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await context.bot.send_message(chat_id=update.effective_chat.id, text="Вы точно хотите удалить анкету? Это действие нельзя отменить!", reply_markup=reply_markup)

async def group(media_group_id: str, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка собранной медиагруппы"""
    
    async with media_group_lock:
        messages = media_group_cache.get(media_group_id, [])
        if media_group_id in media_group_cache:
            del media_group_cache[media_group_id]
        if media_group_id in media_group_tasks:
            del media_group_tasks[media_group_id]
    
    if not messages:
        return
    
    messages.sort(key=lambda msg: msg.message_id)
    media = []
    caption_set = False  # Флаг, чтобы подпись была только у первого элемента
    
    for message in messages:
        if message.caption:
            if len(message.caption) > 1006:
                await message.reply_text(f'Превышен лимит символов! Пожалуйста, сократите своё сообщение на {len(message.caption)-1006} симв.')
                break
        if message.photo:
            file_id = message.photo[-1].file_id
            # Устанавливаем подпись только для первого элемента
            if not caption_set:
                if message.caption:
                    media.append(InputMediaPhoto(
                        media=file_id,
                        caption=message.caption+'\n\n#анкета@adeqmeet',
                        caption_entities=message.caption_entities
                    ))
                else:
                    media.append(InputMediaPhoto(media=file_id, caption='#анкета@adeqmeet'))
            else:
                media.append(InputMediaPhoto(media=file_id))
            caption_set = True
                
        elif message.video:
            file_id = message.video.file_id
            if not caption_set:
                if message.caption:
                    media.append(InputMediaVideo(
                        media=file_id,
                        caption=message.caption+'\n\n#анкета@adeqmeet',
                        caption_entities=message.caption_entities
                    ))
                else:
                    media.append(InputMediaVideo(media=file_id, caption='#анкета@adeqmeet'))
            else:
                media.append(InputMediaVideo(media=file_id))
            caption_set = True
    
    if media:
        keyboard = [
        [InlineKeyboardButton("✅ Принять", callback_data=f"mod.accept-{update.effective_user.id}"), InlineKeyboardButton("❌ Отклонить", callback_data=f"mod.deny-{update.effective_user.id}")],
        [InlineKeyboardButton("💥 Забанить", callback_data=f"mod.ban-{update.effective_user.id}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        msg = await context.bot.send_media_group(chat_id=ADMIN, media=media)
        await msg[0].reply_text('Выберите действие:', reply_markup=reply_markup)
        db[str(update.effective_user.id)]['status'] = 'pending'
        await update.message.reply_text('Анкета отправлена! Ожидайте.')
        with open('db.json', 'w', encoding='utf-8') as fp:
            json.dump(db, fp, indent=2, ensure_ascii=False)

async def form(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка всех типов сообщений"""
    message = update.message
    bot = context.bot
    if db[str(update.effective_user.id)]['ban']:
        await message.reply_text('К сожалению, вы не можете отправлять новые анкеты.')
        return
    if db[str(update.effective_user.id)]['status'] == 'pending':
        await message.reply_text('Админы ещё не проверили вашу анкету!\nЕсли вы хотите изменить свою анкету, придётся дождаться её одобрения (или отклонения).')
        return
    
    # Обработка медиагрупп (альбомов)
    if message.media_group_id:

        media_group_id = message.media_group_id
        async with media_group_lock:
            media_group_cache[media_group_id].append(message)
            if media_group_id not in media_group_tasks:
                media_group_tasks[media_group_id] = asyncio.create_task(
                    group(media_group_id, update, context)
                )
        return
    keyboard = [
    [InlineKeyboardButton("✅ Принять", callback_data=f"mod.accept-{update.effective_user.id}"), InlineKeyboardButton("❌ Отклонить", callback_data=f"mod.deny-{update.effective_user.id}")],
    [InlineKeyboardButton("💥 Забанить", callback_data=f"mod.ban-{update.effective_user.id}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    # Обработка одиночных сообщений
    if message.text:
        if len(message.text) > 4078:
            await message.reply_text(f'Превышен лимит символов! Пожалуйста, сократите своё сообщение на {len(message.text)-4078} симв.')
            return
        await bot.send_message(ADMIN, message.text+'\n\n#анкета@adeqmeet', entities=message.entities, reply_markup=reply_markup, disable_web_page_preview=True)
    else:
        if message.caption:
            if len(message.caption) > 1006:
                await message.reply_text(f'Превышен лимит символов! Пожалуйста, сократите своё сообщение на {len(message.caption)-1006} симв.')
                return
        if message.photo:
            await bot.send_photo(ADMIN, message.photo[-1].file_id, message.caption+'\n\n#анкета@adeqmeet' if message.caption else '#анкета@adeqmeet', caption_entities=message.caption_entities, reply_markup=reply_markup)
        elif message.video:
            await bot.send_video(ADMIN, message.video.file_id, caption=message.caption+'\n\n#анкета@adeqmeet' if message.caption else '#анкета@adeqmeet', caption_entities=message.caption_entities, reply_markup=reply_markup)
        elif message.audio:
            await bot.send_audio(ADMIN, message.audio.file_id, caption=message.caption+'\n\n#анкета@adeqmeet' if message.caption else '#анкета@adeqmeet', caption_entities=message.caption_entities, reply_markup=reply_markup)
        elif message.document:
            await bot.send_document(ADMIN, message.document.file_id, message.caption+'\n\n#анкета@adeqmeet' if message.caption else '#анкета@adeqmeet', caption_entities=message.caption_entities, reply_markup=reply_markup)
        else:
            await message.reply_text('Ну и нахер вы это отправили?\nОтправьте нормальную анкету, тогда поговорим.')
            return
    db[str(update.effective_user.id)]['status'] = 'pending'
    await message.reply_text('Анкета отправлена! Ожидайте.')
    with open('db.json', 'w', encoding='utf-8') as fp:
        json.dump(db, fp, indent=2, ensure_ascii=False)

async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        action, user_id = query.data.split('-')
    except:
        action = query.data

    if action == 'delete.cancel':
        await query.edit_message_text("Удаление отменено.")
    if action == 'delete.accept':
        try:
            if isinstance(db[str(update.effective_user.id)]['msg_id'], list):
                await context.bot.delete_messages(CHANNEL, db[str(update.effective_user.id)]['msg_id'])
            else:
                await context.bot.delete_message(CHANNEL, db[str(update.effective_user.id)]['msg_id'])
            db[str(update.effective_user.id)]['msg_id'] = None
            db[str(update.effective_user.id)]['status'] = 'unpub'
            await query.edit_message_text(text=f"Ваша анкета удалена. Желаем успехов!\n(если надумаете вернуться, вы всё ещё можете отправить новую анкету)")
        except:
            await context.bot.send_message(ADMIN, f'Поступил запрос на удаление анкеты:\nt.me/c/{str(CHANNEL)[4:]}/{db[str(update.effective_user.id)]['msg_id']}')
            db[str(update.effective_user.id)]['msg_id'] = None
            db[str(update.effective_user.id)]['status'] = 'unpub'
            await query.edit_message_text(text=f"Ваша анкета отмечена на удаление. Желаем успехов!\n(если надумаете вернуться, вы всё ещё можете отправить новую анкету)")
        with open('db.json', 'w', encoding='utf-8') as fp:
            json.dump(db, fp, indent=2, ensure_ascii=False)
    
    if action == 'mod.deny':
        if query.message.reply_to_message:
            try:
                await query.message.reply_to_message.delete()
            except:
                pass
        try:
            await query.delete_message()
        except:
            if query.message.caption:
                await query.edit_message_caption('Анкета отклонена.')
            else:
                await query.edit_message_text('Анкета отклонена.')
        if db[user_id]['msg_id']:
            db[user_id]['status'] = 'pub'
        else:
            db[user_id]['status'] = 'unpub'
        await context.bot.send_message(db[user_id]['chat_id'], 'Вашу анкету отклонили. Измените её и отправьте ещё раз.')
        with open('db.json', 'w', encoding='utf-8') as fp:
            json.dump(db, fp, indent=2, ensure_ascii=False)
    if action == 'mod.accept':
        if db[user_id]['msg_id']:
            try:
                if isinstance(db[user_id]['msg_id'], list):
                    await context.bot.delete_messages(CHANNEL, db[user_id]['msg_id'])
                else:
                    await context.bot.delete_message(CHANNEL, db[user_id]['msg_id'])
            except:
                await context.bot.send_message(ADMIN, f'Поступил запрос на удаление анкеты:\nt.me/c/{str(CHANNEL)[4:]}/{db[user_id]['msg_id']}')
        if query.message.reply_to_message:
            msgs = []
            for ids in range(query.message.reply_to_message.message_id, query.message.message_id):
                msgs.append(ids)
            msg = await context.bot.copy_messages(CHANNEL, ADMIN, msgs)
            db[user_id]['msg_id'] = []
            for ids in msg:
                db[user_id]['msg_id'].append(ids.message_id)
            msg = msg[0]
            try:
                await query.message.reply_to_message.delete()
            except:
                pass
        else:
            msg = await context.bot.copy_message(CHANNEL, ADMIN, query.message.message_id)
            db[user_id]['msg_id'] = msg.message_id
        try:
            await query.delete_message()
        except:
            if query.message.caption:
                await query.edit_message_caption('Анкета принята.')
            else:
                await query.edit_message_text('Анкета принята.')
        db[user_id]['status'] = 'pub'
        await context.bot.send_message(db[user_id]['chat_id'], f'Вашу анкету приняли! Она доступна по этой ссылке:\nt.me/c/{CHANNEL[4:]}/{msg.message_id}\nЕсли вы хотите удалить свою анкету, воспользуйтесь /delete.')
        with open('db.json', 'w', encoding='utf-8') as fp:
            json.dump(db, fp, indent=2, ensure_ascii=False)
    if action == 'mod.ban':
        db[user_id]['ban'] = True
        if db[user_id]['msg_id']:
            db[user_id]['status'] = 'pub'
        else:
            db[user_id]['status'] = 'unpub'
        try:
            await query.delete_message()
        except:
            if query.message.caption:
                await query.edit_message_caption('Пользователь забанен.')
            else:
                await query.edit_message_text('Пользователь забанен.')
        with open('db.json', 'w', encoding='utf-8') as fp:
            json.dump(db, fp, indent=2, ensure_ascii=False)


token = open('token.txt', 'r').readline()
if '/n' in token:
    token = token[:-2]
if __name__ == '__main__':
    application = Application.builder().token(token).build()

    application.add_handlers([CommandHandler('start', start),
                              CommandHandler('delete', delete),
                              CommandHandler('help', help),
                              CommandHandler('unban', unban),
                              CallbackQueryHandler(buttons),
                              MessageHandler(~filters.COMMAND&filters.ChatType.PRIVATE, form)])
    
    application.run_polling()
with open('db.json', 'w', encoding='utf-8') as fp:
    json.dump(db, fp, indent=2, ensure_ascii=False)