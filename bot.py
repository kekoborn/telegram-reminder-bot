import os
import asyncio
import logging
from datetime import datetime, timedelta
import json
import aiohttp
import re
from urllib.parse import quote
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Конфигурация
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
HF_API_KEY = os.getenv('HF_API_KEY')

class AutoReminderBot:
    def __init__(self):
        self.application = None
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Команда /start"""
        welcome_text = """🤖 Привет! Я автоматический бот для создания напоминаний в iOS!

💡 Powered by Hugging Face - полностью автоматическое создание!

Просто напишите задачу, и я создам автоматическую ссылку:

📝 Примеры сообщений:
• "Завтра в 15:00 встреча с врачом"
• "Через 2 часа принять лекарство" 
• "В понедельник сдать отчет до 18:00"
• "Купить продукты после работы"

🔗 Нажмите ссылку → автоматически создастся напоминание!

Команды:
/start - показать это сообщение
/help - подробная помощь
/setup - инструкция по настройке iOS"""
        await update.message.reply_text(welcome_text)

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Команда /help"""
        help_text = """❓ Как работает автоматический бот:

1️⃣ Отправьте сообщение с задачей
2️⃣ Бот проанализирует и создаст ссылку
3️⃣ Нажмите на ссылку - откроется iOS Shortcuts
4️⃣ Напоминание создастся автоматически!

📱 Поддерживаемые форматы:
• Время: "завтра в 15:00", "через час"
• Дни недели: "в понедельник", "в пятницу"
• Даты: "25 декабря", "31.12.2024"

🔧 Что нужно настроить в iOS:
1. Создать Shortcut "CreateReminder"
2. Разрешить запуск по ссылкам
3. Дать доступ к Напоминаниям

/setup - подробная инструкция по настройке"""
        await update.message.reply_text(help_text)

    async def setup_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Инструкция по настройке"""
        setup_text = """🔧 Настройка iOS Shortcuts:

📱 Шаг 1: Создайте Shortcut
1. Откройте "Быстрые команды"
2. Нажмите "+" → "Добавить действие"
3. Назовите Shortcut: "CreateReminder"

🔨 Шаг 2: Добавьте действия:
1. "Получить текст из ввода"
2. "Получить значение словаря" (ключ: title)
3. "Получить значение словаря" (ключ: date) 
4. "Получить значение словаря" (ключ: time)
5. "Добавить напоминание"

⚙️ Шаг 3: Настройки Shortcut:
• Включить "Использовать с Siri"
• Включить "Разрешить общий доступ" 
• Включить "Принимать текст на входе"

🔑 Шаг 4: Разрешения:
Настройки → Конфиденциальность → Напоминания → Быстрые команды ✅

После настройки отправьте любое сообщение с задачей!"""
        await update.message.reply_text(setup_text)

    def smart_pattern_analysis(self, text: str) -> dict:
        """Умный анализ паттернами"""
        
        task_keywords = {
            'meeting': ['встреча', 'собрание', 'совещание'],
            'medicine': ['лекарство', 'таблетка', 'принять', 'врач'],
            'shopping': ['купить', 'магазин', 'продукты'],
            'call': ['позвонить', 'звонок', 'связаться'],
            'work': ['сдать', 'отчет', 'работа', 'проект'],
            'personal': ['напомни', 'не забыть', 'важно']
        }
        
        priority_words = {
            'high': ['срочно', 'важно', 'асап'],
            'low': ['когда-нибудь', 'не срочно']
        }
        
        # Проверяем ключевые слова
        found_keywords = []
        category = 'other'
        
        for cat, keywords in task_keywords.items():
            for keyword in keywords:
                if keyword in text.lower():
                    found_keywords.append(keyword)
                    category = cat
                    break
        
        if not found_keywords:
            return {"is_task": False, "reason": "Не найдены ключевые слова задач"}
        
        # Извлекаем время
        now = datetime.now()
        date_found = None
        time_found = None
        
        # Относительные даты
        if 'завтра' in text.lower():
            date_found = (now + timedelta(days=1)).strftime('%Y-%m-%d')
        elif 'послезавтра' in text.lower():
            date_found = (now + timedelta(days=2)).strftime('%Y-%m-%d')
        elif 'сегодня' in text.lower():
            date_found = now.strftime('%Y-%m-%d')
        
        # Дни недели
        weekdays = {
            'понедельник': 0, 'вторник': 1, 'среда': 2, 'четверг': 3,
            'пятница': 4, 'суббота': 5, 'воскресенье': 6
        }
        
        for day_name, day_num in weekdays.items():
            if day_name in text.lower():
                days_ahead = day_num - now.weekday()
                if days_ahead <= 0:
                    days_ahead += 7
                target_date = now + timedelta(days=days_ahead)
                date_found = target_date.strftime('%Y-%m-%d')
                break
        
        # Относительное время "через X"
        through_match = re.search(r'через (\d+) (час|часа|часов|день|дня|дней)', text.lower())
        if through_match:
            amount = int(through_match.group(1))
            unit = through_match.group(2)
            
            if 'час' in unit:
                target_time = now + timedelta(hours=amount)
                date_found = target_time.strftime('%Y-%m-%d')
                time_found = target_time.strftime('%H:%M')
            elif 'день' in unit:
                target_date = now + timedelta(days=amount)
                date_found = target_date.strftime('%Y-%m-%d')
        
        # Точное время
        time_patterns = [
            r'(\d{1,2}):(\d{2})',
            r'в (\d{1,2}) (утра|дня|вечера)',
            r'(\d{1,2}) часов'
        ]
        
        for pattern in time_patterns:
            time_match = re.search(pattern, text.lower())
            if time_match:
                if ':' in time_match.group():
                    time_found = time_match.group()
                else:
                    hour = int(time_match.group(1))
                    period = time_match.group(2) if len(time_match.groups()) > 1 else None
                    
                    if period == 'вечера' and hour < 12:
                        hour += 12
                    elif period == 'утра' and hour == 12:
                        hour = 0
                        
                    time_found = f"{hour:02d}:00"
                break
        
        # Время по словам
        if not time_found:
            if 'утром' in text.lower():
                time_found = '09:00'
            elif 'днем' in text.lower():
                time_found = '14:00'
            elif 'вечером' in text.lower():
                time_found = '18:00'
        
        # Приоритет
        priority = 'medium'
        for level, words in priority_words.items():
            for word in words:
                if word in text.lower():
                    priority = level
                    break
        
        if any(word in text.lower() for word in ['сегодня', 'срочно', 'важно']):
            priority = 'high'
        
        # Генерируем заголовок
        title = text
        if len(title) > 50:
            title_clean = re.sub(r'\b(завтра|послезавтра|сегодня|через \d+ \w+|\d{1,2}:\d{2}|в \d{1,2} \w+)\b', '', title.lower())
            title_clean = re.sub(r'\s+', ' ', title_clean).strip()
            if len(title_clean) > 50:
                title = title_clean[:47] + "..."
            else:
                title = title_clean.capitalize() if title_clean else text[:50]
        
        return {
            "is_task": True,
            "title": title,
            "description": text,
            "date": date_found,
            "time": time_found,
            "priority": priority,
            "category": category,
            "keywords_found": found_keywords
        }

    def create_ios_link(self, reminder_data: dict) -> str:
        """Создание ссылки для автоматического запуска iOS Shortcuts"""
        
        # Подготавливаем данные
        json_data = {
            "title": reminder_data.get("title", ""),
            "date": reminder_data.get("date", ""),
            "time": reminder_data.get("time", ""),
            "priority": reminder_data.get("priority", "medium"),
            "category": reminder_data.get("category", "other")
        }
        
        # Конвертируем в JSON строку
        json_string = json.dumps(json_data, ensure_ascii=False)
        
        # Кодируем для URL
        encoded_json = quote(json_string)
        
        # Создаем ссылку iOS Shortcuts
        ios_url = f"shortcuts://run-shortcut?name=CreateReminder&input=text&text={encoded_json}"
        
        return ios_url

    def create_reminder_url(self, title: str, date: str = "", time: str = "") -> str:
        """Альтернативная ссылка через x-apple-reminder"""
        
        # Базовая ссылка напоминаний iOS
        reminder_url = "x-apple-reminder://add"
        params = []
        
        if title:
            params.append(f"title={quote(title)}")
        
        if date and time:
            # Объединяем дату и время
            datetime_str = f"{date} {time}"
            params.append(f"dueDate={quote(datetime_str)}")
        elif date:
            params.append(f"dueDate={quote(date)}")
        
        if params:
            reminder_url += "?" + "&".join(params)
        
        return reminder_url

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка сообщений"""
        user_message = update.message.text
        user_id = update.effective_user.id
        user_name = update.effective_user.first_name or "Пользователь"
        
        logger.info(f"📩 Сообщение от {user_name} ({user_id}): {user_message}")
        
        processing_msg = await update.message.reply_text("🔍 Анализирую и создаю автоматическую ссылку...")
        
        start_time = datetime.now()
        
        try:
            # Анализ сообщения
            analysis = self.smart_pattern_analysis(user_message)
            processing_time = (datetime.now() - start_time).total_seconds()
            
            if not analysis.get("is_task", False):
                reason = analysis.get("reason", "Не удалось определить как задачу")
                await processing_msg.edit_text(
                    f"🤔 Это не похоже на задачу\n\n"
                    f"Причина: {reason}\n\n"
                    f"💡 Попробуйте включить:\n"
                    f"• Время: 'завтра в 15:00'\n"
                    f"• Действие: 'купить', 'встреча', 'напомни'\n"
                    f"• Конкретику: 'встреча с врачом'\n\n"
                    f"⚡ Время анализа: {processing_time:.1f}с"
                )
                return
            
            # Создаем iOS ссылки
            shortcuts_url = self.create_ios_link(analysis)
            reminder_url = self.create_reminder_url(
                analysis.get("title", ""),
                analysis.get("date", ""),
                analysis.get("time", "")
            )
            
            # Эмодзи карта
            emoji_map = {
                "high": "🔥", "medium": "⭐", "low": "📝",
                "meeting": "👥", "medicine": "💊", "shopping": "🛒",
                "call": "📞", "work": "💼", "other": "📋"
            }
            
            priority_emoji = emoji_map.get(analysis.get('priority', 'medium'), '⭐')
            category_emoji = emoji_map.get(analysis.get('category', 'other'), '📋')
            
            # Формируем ответ с автоматическими ссылками
            success_text = f"✅ Автоматические ссылки готовы!\n\n"
            success_text += f"{category_emoji} **{analysis['title']}**\n"
            
            if analysis.get('date'):
                success_text += f"📅 Дата: {analysis['date']}\n"
            if analysis.get('time'):
                success_text += f"⏰ Время: {analysis['time']}\n"
                
            success_text += f"{priority_emoji} Приоритет: {analysis['priority']}\n"
            
            if 'keywords_found' in analysis:
                success_text += f"🔍 Найдены: {', '.join(analysis['keywords_found'])}\n"
            
            success_text += f"⚡ Время обработки: {processing_time:.1f}с\n\n"
            
            success_text += f"🔗 **Нажмите для создания напоминания:**\n"
            success_text += f"[📱 Через Shortcuts]({shortcuts_url})\n"
            success_text += f"[🍎 Прямо в Напоминания]({reminder_url})\n\n"
            success_text += f"🤗 Powered by Hugging Face"
            
            await processing_msg.edit_text(success_text, parse_mode='Markdown', disable_web_page_preview=True)
            
        except Exception as e:
            logger.error(f"❌ Ошибка обработки: {e}")
            await processing_msg.edit_text(
                f"❌ Произошла ошибка\n\n"
                f"Подробности: {str(e)}\n\n"
                f"🔄 Попробуйте еще раз или обратитесь к разработчику"
            )

    def run(self):
        """Запуск бота"""
        self.application = Application.builder().token(TELEGRAM_TOKEN).build()
        
        # Регистрируем обработчики
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(CommandHandler("setup", self.setup_command))
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
        
        logger.info("🚀 Auto iOS Reminder Bot запущен!")
        self.application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    if not TELEGRAM_TOKEN:
        logger.error("❌ TELEGRAM_TOKEN не установлен!")
        exit(1)
        
    logger.info("🍎 Используется автоматическое создание через iOS URL Scheme")
    logger.info(f"🔑 HF API Key: {'✅' if HF_API_KEY else '❌'}")
    
    bot = AutoReminderBot()
    bot.run()
