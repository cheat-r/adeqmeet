import logging, asyncio, json, os
from collections import defaultdict
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, InputMediaVideo
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, ContextTypes, filters

CHANNEL = '-1002016542799' # Канал, в который будут публиковаться анкеты
ADMIN = '-1002174615446' # Чат администраторов, в который будут приходить анкеты на проверку
OWNER = ['845130333', '425415542'] # Список владельцев (могут редактировать конфиг и управлять админами)

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

media_group_cache = defaultdict(list)
media_group_tasks = {}
media_group_lock = asyncio.Lock()

def dump():
    """Сохранение в базу данных"""
    with open('db.json', 'w', encoding='utf-8') as fp:
        json.dump(db, fp, indent=2, ensure_ascii=False)

if os.path.exists('db.json'):
    with open('db.json', 'r', encoding='utf-8') as fp:
        db = json.load(fp)
else:
    db = {"admins":{},"config":{"premium":False}}
    for n in OWNER:
        db['admins'][n] = 'owner'
    dump()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Первое взаимодействие пользователя с ботом. Добавляет пользователя в базу данных. Во второй и последующий раз ничего не делает"""
    if not str(update.effective_user.id) in db.keys():
        db[str(update.effective_user.id)] = {
            "msg_id": None,
            "status": 'unpub',
            "ban": False
        }
        await update.message.reply_text("Приветствуем! Отправьте сюда свою анкету, и в скором времени мы её выложим!\nЕсли захотите удалить анкету, воспользуйтесь командой /delete.")
        dump()

async def help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Список команд, актуальный для пользователей с разным уровнем полномочий"""
    if not str(update.effective_user.id) in db['admins']:
        await update.message.reply_text("Доступные команды:\nСообщение в ЛС - отправить анкету на проверку\n/delete - удалить собственную анкету")
    else:
        admin = db['admins'][str(update.effective_user.id)]
        await update.message.reply_text(f"Доступные команды:\nСообщение в ЛС - отправить анкету на проверку\n/delete - удалить собственную анкету\n\nКоманды {'модератора' if admin=='mod' else 'администратора' if admin=='admin' else 'владельца'}:\n/approve <id анкеты> [кол-во медиафайлов в анкете] - ручное принятие анкеты (использовать по требованию){'\n/unban <id пользователя> - вернуть пользователю возможность отправлять анкеты' if admin in ('admin','owner') else ''}{'\n/config <настройка> - управление конфигурацией (подробности внутри команды)\n/manage <id пользователя> <mod|admin|remove> - управление пользователем в списке администраторов, назначение на должность и увольнение' if admin == 'owner' else ''}")

async def unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Вернуть пользователю возможность отправлять анкеты"""
    if not str(update.effective_user.id) in db['admins']:
        await update.message.reply_text("Команда доступна только администраторам.")
        return
    if db['admins'][str(update.effective_user.id)] in ('admin', 'owner'):
        if not context.args:
            await update.message.reply_text('Использование: /unban <user_id>')
            return
        if context.args[0] in db:
            if db[context.args[0]]['ban'] == False:
                await update.message.reply_text('Пользователь есть в базе, но он не забанен.')
                return
            db[context.args[0]]['ban'] = False
            await update.message.reply_text("Пользователь разбанен.")
            dump()
        else:
            await update.message.reply_text('Пользователя нет в базе данных или вы неправильно указали айди.')
    else:
        await update.message.reply_text('Вам необходимо быть админом для управления банами.')

async def config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Конфигурация бота. Пока что лишь одна, но может в будущем добавлю ещё :P"""
    if not str(update.effective_user.id) in db['admins']:
        await update.message.reply_text("Команда доступна только администраторам.")
        return
    if db['admins'][str(update.effective_user.id)] == 'owner':
        if not context.args:
            await update.message.reply_text('Доступные конфигурации:\npremium - разрешить пользователям отправлять анкеты с премиум-эмодзи и увеличенным лимитом символов в медиа (Использование: /config premium <true|false>)\n...это всё. :P')
            return
        if context.args[0].lower() == 'premium':
            if len(context.args) > 1:
                if context.args[1].lower() == 'true':
                    db['config']['premium'] = True
                    await update.message.reply_text('Настройка изменена: анкеты с премиумом разрешены.')
                    dump()
                elif context.args[1].lower() == 'false':
                    db['config']['premium'] = False
                    await update.message.reply_text('Настройка изменена: анкеты с премиумом запрещены.')
                    dump()
                else:
                    await update.message.reply_text('Пожалуйста, укажите true или false.')
            else:
                await update.message.reply_text(f'Анкеты с премиумом {'разрешены' if db['config']['premium'] else 'запрещены'}.\nИспользование: /config premium <true|false>')
        else:
            await update.message.reply_text('Неверно указана конфигурация!')
    else:
        await update.message.reply_text('Вам необходимо быть владельцем для управления конфигурацией.')

async def manage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Управление списком администраторов - добавление, изменение, удаление"""
    if not str(update.effective_user.id) in db['admins']:
        await update.message.reply_text(f"Команда доступна только администраторам.")
        return
    if db['admins'][str(update.effective_user.id)] == 'owner':
        if not context.args:
            await update.message.reply_text('Использование: /manage <id> <mod|admin|remove>')
            return
        if context.args[0] == str(update.effective_user.id):
            await update.message.reply_text('Это вы! К сожалению (или счастью), вы не можете управлять собой.')
            return
        if len(context.args) > 1:
            if context.args[0] in db['admins']:
                if db['admins'][context.args[0]] == 'owner':
                    await update.message.reply_text('Вы не можете управлять другим владельцем!')
                    return
            if context.args[1].lower() in ('mod', 'admin'):
                db['admins'][context.args[0]] = context.args[1]
                await update.message.reply_text(f'Пользователь назначен {'модератором' if context.args[1]=='mod' else 'администратором'}.')
                dump()
            elif context.args[1].lower() == 'remove':
                if not context.args[0] in db['admins']:
                    await update.message.reply_text('Пользователя нет в списке администраторов или вы неправильно указали айди.')
                    return
                del db['admins'][context.args[0]]
                await update.message.reply_text('Пользователь удалён из списка администраторов.')
                dump()
            else:
                await update.message.reply_text('Неверно указана команда!')
        else:
            if context.args[0] in db['admins']:
                await update.message.reply_text(f'Пользователь является {'модератором' if db['admins'][context.args[0]] == 'mod' else 'администратором' if db['admins'][context.args[0]] == 'admin' else 'владельцем'}.')
            else:
                await update.message.reply_text('Пользователя нет в списке администраторов или вы неправильно указали айди.')
    else:
        await update.message.reply_text('Вам необходимо быть владельцем для управления администраторами.')

async def delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Запрос удаления собственной анкеты"""
    if db[str(update.effective_user.id)]['status'] == 'pending' or db[str(update.effective_user.id)]['status'] == 'unpub':
        if not db[str(update.effective_user.id)]['msg_id']:
            await update.message.reply_text("Пока что вам нечего удалять...")
        else:
            await update.message.reply_text("Админы ещё проверяют вашу новую анкету!\nНе волнуйтесь, старая анкета будет удалена автоматически после одобрения.\nЕсли вашу анкету всё же не одобрят, воспользуйтесь командой ещё раз.")
        return
    keyboard = [
        [InlineKeyboardButton("💥 Да, удалить!", callback_data="delete.accept"), InlineKeyboardButton("🌻 Нет, я передумал", callback_data="delete.cancel")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Вы точно хотите удалить анкету? Это действие нельзя отменить!", reply_markup=reply_markup)

async def group(media_group_id: str, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка собранной медиагруппы (см. функцию form)"""
    
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
    ids = []
    caption_set = False  # Флаг, чтобы подпись была только у первого элемента
    
    for message in messages:
        if message.caption:
            if len(message.caption) > 1006:
                if db['config']['premium']:
                    if len(message.caption) > 4078:
                        await message.reply_text(f'Превышен лимит символов! Пожалуйста, сократите своё сообщение на {len(message.caption)-4078} симв.')
                        return
                    ids.append(message.id)
                else:
                    await message.reply_text(f'Превышен лимит символов! Пожалуйста, сократите своё сообщение на {len(message.caption)-1006} симв.')
                    return
            elif "<tg-emoji" in message.caption_html:
                if db['config']['premium']:
                    ids.append(message.id)
                else:
                    await message.reply_text('На данный момент мы не можем выкладывать анкеты с премиум-эмодзи. Попробуйте позже или уберите все премиум-эмодзи и попробуйте ещё раз.')
                    return
        if caption_set:
            ids.append(message.id)
                    
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

    if ids:
        msg = await context.bot.forward_messages(ADMIN, update.effective_user.id, ids)
        keyboard_manual = [
        [InlineKeyboardButton("❌ Отклонить", callback_data=f"mod.deny-{update.effective_user.id}")],
        [InlineKeyboardButton("💥 Забанить", callback_data=f"mod.ban-{update.effective_user.id}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard_manual)
        await context.bot.send_message(ADMIN, f'{update.effective_user.full_name} ({'@'+(update.effective_user.username+', ') if update.effective_user.username else ''}{update.effective_user.id})\n(принятие вручную)', reply_to_message_id=msg[0].message_id, reply_markup=reply_markup)
        db[str(update.effective_user.id)]['status'] = 'pending'
        await update.message.reply_text('Анкета отправлена! Ожидайте.')
        dump()
        return
    if media:
        keyboard = [
        [InlineKeyboardButton("✅ Принять", callback_data=f"mod.accept-{update.effective_user.id}"), InlineKeyboardButton("❌ Отклонить", callback_data=f"mod.deny-{update.effective_user.id}")],
        [InlineKeyboardButton("💥 Забанить", callback_data=f"mod.ban-{update.effective_user.id}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        msg = await context.bot.send_media_group(chat_id=ADMIN, media=media)
        await msg[0].reply_text(f'{update.effective_user.full_name} ({'@'+(update.effective_user.username+', ') if update.effective_user.username else ''}{update.effective_user.id})', reply_markup=reply_markup)
        db[str(update.effective_user.id)]['status'] = 'pending'
        await update.message.reply_text('Анкета отправлена! Ожидайте.')
        dump()

async def form(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка анкеты и последующая отправка на модерацию"""
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
    keyboard_manual = [
    [InlineKeyboardButton("❌ Отклонить", callback_data=f"mod.deny-{update.effective_user.id}")],
    [InlineKeyboardButton("💥 Забанить", callback_data=f"mod.ban-{update.effective_user.id}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    # Обработка одиночных сообщений
    if message.text:
        if len(message.text) > 4078:
            await message.reply_text(f'Превышен лимит символов! Пожалуйста, сократите своё сообщение на {len(message.text)-4078} симв.')
            return
        if "<tg-emoji" in message.text_html:
            if db['config']['premium']:
                msg = await bot.forward_message(ADMIN, update.effective_user.id, update.message.id)
                reply_markup = InlineKeyboardMarkup(keyboard_manual)
                await msg.reply_text(f'{update.effective_user.full_name} ({'@'+(update.effective_user.username+', ') if update.effective_user.username else ''}{update.effective_user.id})\n(принятие вручную)', reply_markup=reply_markup)
            else:
                await message.reply_text('На данный момент мы не можем выкладывать анкеты с премиум-эмодзи. Попробуйте позже или уберите все премиум-эмодзи и попробуйте ещё раз.')
                return
        else:        
            msg = await bot.send_message(ADMIN, message.text+'\n\n#анкета@adeqmeet', entities=message.entities, disable_web_page_preview=True)
            await msg.reply_text(f'{update.effective_user.full_name} ({'@'+(update.effective_user.username+', ') if update.effective_user.username else ''}{update.effective_user.id})', reply_markup=reply_markup)
    else:
        if message.caption:
            if len(message.caption) > 1006 and not db['config']['premium']:
                await message.reply_text(f'Превышен лимит символов! Пожалуйста, сократите своё сообщение на {len(message.caption)-1006} симв.')
                return
            elif len(message.caption) > 4078:
                await message.reply_text(f'Превышен лимит символов! Пожалуйста, сократите своё сообщение на {len(message.caption)-4078} симв.')
                return
            if "<tg-emoji" in message.caption_html:
                if db['config']['premium']:
                    msg = await bot.forward_message(ADMIN, update.effective_user.id, update.message.id)
                    reply_markup = InlineKeyboardMarkup(keyboard_manual)
                    await msg.reply_text(f'{update.effective_user.full_name} ({'@'+(update.effective_user.username+', ') if update.effective_user.username else ''}{update.effective_user.id})\n(принятие вручную)', reply_markup=reply_markup)
                    db[str(update.effective_user.id)]['status'] = 'pending'
                    await message.reply_text('Анкета отправлена! Ожидайте.')
                    dump()
                    return
                else:
                    await message.reply_text('На данный момент мы не можем выкладывать анкеты с премиум-эмодзи. Попробуйте позже или уберите все премиум-эмодзи и попробуйте ещё раз.')
                    return
        if message.photo:
            msg = await bot.send_photo(ADMIN, message.photo[-1].file_id, message.caption+'\n\n#анкета@adeqmeet' if message.caption else '#анкета@adeqmeet', caption_entities=message.caption_entities)
        elif message.video:
            msg = await bot.send_video(ADMIN, message.video.file_id, caption=message.caption+'\n\n#анкета@adeqmeet' if message.caption else '#анкета@adeqmeet', caption_entities=message.caption_entities)
        elif message.audio:
            msg = await bot.send_audio(ADMIN, message.audio.file_id, caption=message.caption+'\n\n#анкета@adeqmeet' if message.caption else '#анкета@adeqmeet', caption_entities=message.caption_entities)
        elif message.document:
            msg = await bot.send_document(ADMIN, message.document.file_id, message.caption+'\n\n#анкета@adeqmeet' if message.caption else '#анкета@adeqmeet', caption_entities=message.caption_entities)
        else:
            await message.reply_text('Я не думаю, что это сюда впишется.')
            return
        await msg.reply_text(f'{update.effective_user.full_name} ({'@'+(update.effective_user.username+', ') if update.effective_user.username else ''}{update.effective_user.id})', reply_markup=reply_markup)
    db[str(update.effective_user.id)]['status'] = 'pending'
    await message.reply_text('Анкета отправлена! Ожидайте.')
    dump()

async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Действия по нажатию кнопок"""
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
            await context.bot.send_message(ADMIN, f'Поступил запрос на удаление анкеты:\nt.me/c/{CHANNEL[4:]}/{db[str(update.effective_user.id)]['msg_id']}')
            db[str(update.effective_user.id)]['msg_id'] = None
            db[str(update.effective_user.id)]['status'] = 'unpub'
            await query.edit_message_text(text=f"Ваша анкета отмечена на удаление. Желаем успехов!\n(если надумаете вернуться, вы всё ещё можете отправить новую анкету)")
        dump()
    
    if action == 'mod.deny':
        if not str(update.effective_user.id) in db['admins']:
            return
        await query.edit_message_text(f'{query.message.text}\nАнкета отклонена {update.effective_user.full_name}')
        if db[user_id]['msg_id']:
            db[user_id]['status'] = 'pub'
        else:
            db[user_id]['status'] = 'unpub'
        await context.bot.send_message(user_id, 'Вашу анкету отклонили. Измените её и отправьте ещё раз.')
        dump()
    if action == 'mod.accept':
        if not str(update.effective_user.id) in db['admins']:
            return
        if db[user_id]['msg_id']:
            try:
                await context.bot.delete_messages(CHANNEL, db[user_id]['msg_id'])
            except:
                await context.bot.send_message(ADMIN, f'Поступил запрос на удаление анкеты:\nt.me/c/{CHANNEL[4:]}/{db[user_id]['msg_id'][0]}')
        msgs = []
        for ids in range(query.message.reply_to_message.message_id, query.message.message_id):
            msgs.append(ids)
        msg = await context.bot.copy_messages(CHANNEL, ADMIN, msgs)
        db[user_id]['msg_id'] = []
        for ids in msg:
            db[user_id]['msg_id'].append(ids.message_id)
        msg = msg[0]
        await query.edit_message_text(f'{query.message.text}\nАнкета принята {update.effective_user.full_name}')
        db[user_id]['status'] = 'pub'
        await context.bot.send_message(user_id, f'Вашу анкету приняли! Она доступна по этой ссылке:\nt.me/c/{CHANNEL[4:]}/{msg.message_id}\nЕсли вы хотите удалить свою анкету, воспользуйтесь /delete.')
        dump()
    if action == 'mod.ban':
        if not str(update.effective_user.id) in db['admins']:
            return
        if db['admins'][str(update.effective_user.id)] in ('admin', 'owner'):
            db[user_id]['ban'] = True
            if db[user_id]['msg_id']:
                db[user_id]['status'] = 'pub'
            else:
                db[user_id]['status'] = 'unpub'
            await query.edit_message_text(f'{query.message.text}\nПользователь забанен {update.effective_user.full_name}')
            dump()

async def approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ручное принятие анкеты (для анкет от пользователей с подпиской)"""
    message = update.message
    if not str(update.effective_user.id) in db['admins']:
        await message.reply_text(f"Команда доступна только администраторам.")
        return
    if not message.reply_to_message:
        await message.reply_text('Использование: /manual <id> [кол-во медиафайлов (необяз.)]\nКоманда должна быть ответом на сообщение с кнопками!')
        return
    if message.reply_to_message.from_user.id != context.bot.id or not message.reply_to_message.reply_markup:
        await message.reply_text('Команда должна отвечать на сообщение с кнопками той анкеты, которую вы хотите принять!')
        return
    if not context.args:
        await message.reply_text('Вы не указали айди выложенной анкеты!')
        return
    
    if len(context.args) > 1:
        try:
            last_id = int(context.args[0]) + int(context.args[1]) - 1
            await context.bot.set_message_reaction(CHANNEL, last_id, '🔥')
        except:
            await message.reply_text('Не удалось проверить сообщение. Либо айди неправильный, либо реакции отключены, либо это промах с моей стороны.')
            return
        await context.bot.set_message_reaction(CHANNEL, last_id)
    try:
        await context.bot.set_message_reaction(CHANNEL, int(context.args[0]), '🔥')
    except:
        await message.reply_text('Не удалось проверить сообщение. Либо айди неправильный, либо реакции отключены, либо это промах с моей стороны.')
        return
    await context.bot.set_message_reaction(CHANNEL, int(context.args[0]))

    _, user_id = message.reply_to_message.reply_markup.inline_keyboard[0][0].callback_data.split('-')
    if db[user_id]['msg_id']:
        try:
            await context.bot.delete_messages(CHANNEL, db[user_id]['msg_id'])
        except:
            await context.bot.send_message(ADMIN, f'Поступил запрос на удаление анкеты:\nt.me/c/{CHANNEL[4:]}/{db[user_id]['msg_id'][0]}')
    if len(context.args) > 1:
        db[user_id]['msg_id'] = []
        for x in range(int(context.args[0]), int(context.args[0])+int(context.args[1])):
            db[user_id]['msg_id'].append(x)
    else:
        db[user_id]['msg_id'] = [context.args[0]]
    db[user_id]['status'] = 'pub'
    await message.reply_to_message.edit_text(f'{message.reply_to_message.text}\nАнкета принята {update.effective_user.full_name}')
    await context.bot.send_message(user_id, f'Вашу анкету приняли! Она доступна по этой ссылке:\nt.me/c/{CHANNEL[4:]}/{context.args[0]}\nЕсли вы хотите удалить свою анкету, воспользуйтесь /delete.')
    dump()

token = open('token.txt', 'r').readline()
if '\n' in token:
    token = token[:-1]
if __name__ == '__main__':
    application = Application.builder().token(token).build()

    application.add_handlers([CommandHandler('start', start),
                              CommandHandler('delete', delete),
                              CommandHandler('help', help),
                              CommandHandler('unban', unban),
                              CommandHandler('config', config),
                              CommandHandler('manage', manage),
                              CommandHandler('approve', approve),
                              CallbackQueryHandler(buttons),
                              MessageHandler(~filters.COMMAND&filters.ChatType.PRIVATE, form)])
    
    application.run_polling()
dump()
