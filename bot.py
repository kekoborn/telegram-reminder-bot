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

class FullyAutoReminderBot:
    def __init__(self):
        self.application = None
        self.reminders_db = []  # Простое хранилище напоминаний
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Команда /start"""
        welcome_text = """Привет! Я полностью автоматический бот для напоминаний!

Просто пишите задачи - я создаю специальные сообщения которые можно легко копировать в iOS Reminders одним тапом.

Примеры:
• "Завтра в 15:00 встреча с врачом"
• "Через 2 часа принять лекарство"
• "В понедельник сдать отчет"

Команды:
/start - это сообщение
/list - показать все созданные напоминания
/clear - очистить список"""
        await update.message.reply_text(welcome_text)

    async def list_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показать список всех напоминаний"""
        if not self.reminders_db:
            await update.message.reply_text("У вас пока нет созданных напоминаний.")
            return
        
        reminders_text = "Ваши напоминания:\n\n"
        for i, reminder in enumerate(self.reminders_db[-10:], 1):  # Последние 10
            date_time = ""
            if reminder.get('date'):
                date_time += f" ({reminder['date']}"
                if reminder.get('time'):
                    date_time += f" в {reminder['time']}"
                date_time += ")"
            
            reminders_text += f"{i}. {reminder['title']}{date_time}\n"
        
        await update.message.reply_text(reminders_text)

    async def clear_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Очистить список напоминаний"""
        self.reminders_db.clear()
        await update.message.reply_text("Список напоминаний очищен!")

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

    def format_reminder_for_ios(self, reminder_data: dict) -> str:
        """Форматирует напоминание для легкого копирования в iOS"""
        
        title = reminder_data.get('title', '')
        date = reminder_data.get('date', '')
        time = reminder_data.get('time', '')
        
        # Создаем текст для копирования
        reminder_text = title
        
        if date or time:
            reminder_text += " ("
            if date:
                # Конвертируем дату в читаемый формат
                try:
                    date_obj = datetime.strptime(date, '%Y-%m-%d')
                    readable_date = date_obj.strftime('%d.%m.%Y')
                    reminder_text += readable_date
                except:
                    reminder_text += date
            
            if time:
                if date:
                    reminder_text += f" в {time}"
                else:
                    reminder_text += time
            
            reminder_text += ")"
        
        return reminder_text

    async def create_ios_reminder_message(self, reminder_data: dict, update: Update):
        """Создает сообщение с автоматическим напоминанием"""
        
        # Форматируем для iOS
        ios_text = self.format_reminder_for_ios(reminder_data)
        
        # Создаем красивое сообщение
        message = f"Напоминание создано!\n\n"
        message += f"Скопируйте текст ниже и вставьте в iOS Reminders:\n\n"
        message += f"`{ios_text}`\n\n"
        message += f"Или нажмите и удерживайте текст выше, выберите 'Копировать', затем откройте Напоминания и создайте новое напоминание."
        
        await update.message.reply_text(message, parse_mode='Markdown')
        
        # Отправляем отдельное сообщение только с текстом для удобного копирования
        await update.message.reply_text(ios_text)

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка сообщений"""
        user_message = update.message.text
        user_id = update.effective_user.id
        user_name = update.effective_user.first_name or "Пользователь"
        
        logger.info(f"Сообщение от {user_name} ({user_id}): {user_message}")
        
        processing_msg = await update.message.reply_text("Анализирую и создаю напоминание...")
        
        start_time = datetime.now()
        
        try:
            # Анализ сообщения
            analysis = self.smart_pattern_analysis(user_message)
            processing_time = (datetime.now() - start_time).total_seconds()
            
            if not analysis.get("is_task", False):
                reason = analysis.get("reason", "Не удалось определить как задачу")
                await processing_msg.edit_text(
                    f"Это не похоже на задачу\n\n"
                    f"Причина: {reason}\n\n"
                    f"Попробуйте включить:\n"
                    f"• Время: 'завтра в 15:00'\n"
                    f"• Действие: 'купить', 'встреча', 'напомни'\n"
                    f"• Конкретику: 'встреча с врачом'"
                )
                return
            
            # Сохраняем напоминание
            self.reminders_db.append(analysis)
            
            # Эмодзи карта
            emoji_map = {
                "high": "🔥", "medium": "⭐", "low": "📝",
                "meeting": "👥", "medicine": "💊", "shopping": "🛒",
                "call": "📞", "work": "💼", "other": "📋"
            }
            
            category_emoji = emoji_map.get(analysis.get('category', 'other'), '📋')
            
            # Информационное сообщение
            info_text = f"✅ Напоминание проанализировано!\n\n"
            info_text += f"{category_emoji} {analysis['title']}\n"
            
            if analysis.get('date'):
                info_text += f"📅 Дата: {analysis['date']}\n"
            if analysis.get('time'):
                info_text += f"⏰ Время: {analysis['time']}\n"
            
            info_text += f"⚡ Время обработки: {processing_time:.1f}с\n"
            info_text += f"💾 Сохранено в базу (всего: {len(self.reminders_db)})"
            
            await processing_msg.edit_text(info_text)
            
            # Создаем сообщение для iOS
            await self.create_ios_reminder_message(analysis, update)
            
        except Exception as e:
            logger.error(f"Ошибка обработки: {e}")
            await processing_msg.edit_text(f"Произошла ошибка: {str(e)}")

    def run(self):
        """Запуск бота"""
        self.application = Application.builder().token(TELEGRAM_TOKEN).build()
        
        # Регистрируем обработчики
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("list", self.list_command))
        self.application.add_handler(CommandHandler("clear", self.clear_command))
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
        
        logger.info("🚀 Fully Auto Reminder Bot запущен!")
        self.application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    if not TELEGRAM_TOKEN:
        logger.error("TELEGRAM_TOKEN не установлен!")
        exit(1)
        
    logger.info("📱 Используется полностью автоматическое создание напоминаний")
    logger.info(f"🔑 HF API Key: {'✅' if HF_API_KEY else '❌'}")
    
    bot = FullyAutoReminderBot()
    bot.run()
