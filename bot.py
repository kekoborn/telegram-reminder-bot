import os
import asyncio
import logging
from datetime import datetime, timedelta
import json
import aiohttp
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import google.generativeai as genai

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Конфигурация (переменные окружения)
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
IOS_WEBHOOK_URL = os.getenv('IOS_WEBHOOK_URL')  # URL для iOS Shortcuts

# Инициализация Gemini
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-pro')

class ReminderBot:
    def __init__(self):
        self.application = None
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Команда /start"""
        welcome_text = """
🤖 Привет! Я бот для создания напоминаний в iOS!

Просто отправь мне сообщение с задачей, например:
• "Напомни завтра в 15:00 купить молоко"
• "Встреча с врачом в пятницу в 10 утра"
• "Позвонить маме через час"

Команды:
/start - это сообщение
/help - помощь
        """
        await update.message.reply_text(welcome_text)

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Команда /help"""
        help_text = """
❓ Как использовать бота:

1. Отправьте текстовое сообщение с описанием задачи
2. Бот проанализирует и извлечет:
   - Текст напоминания
   - Дату и время
   - Приоритет

3. Напоминание будет добавлено в iOS через Shortcuts

Примеры сообщений:
• "Завтра в 9 утра встреча с клиентом"
• "Через 2 часа принять лекарство"
• "В понедельник сдать отчет"
• "15 мая день рождения у Анны"
        """
        await update.message.reply_text(help_text)

    async def analyze_message_with_ai(self, text: str) -> dict:
        """Анализ сообщения с помощью Gemini AI"""
        prompt = f"""
Проанализируй следующее сообщение и определи, является ли это задачей или напоминанием.
Если да, извлеки следующую информацию в формате JSON:

{{
    "is_task": true/false,
    "title": "краткое описание задачи",
    "description": "полное описание",
    "date": "YYYY-MM-DD или null",
    "time": "HH:MM или null",
    "priority": "high/medium/low",
    "relative_time": "через X часов/дней или null"
}}

Сообщение: "{text}"

Текущая дата и время: {datetime.now().strftime('%Y-%m-%d %H:%M')}

Если указано относительное время (завтра, через час), вычисли точную дату и время.
Отвечай только JSON, без дополнительного текста.
        """
        
        try:
            response = model.generate_content(prompt)
            result = json.loads(response.text.strip())
            return result
        except Exception as e:
            logger.error(f"Ошибка анализа AI: {e}")
            return {"is_task": False, "error": str(e)}

    def calculate_absolute_time(self, relative_time: str) -> dict:
        """Вычисление абсолютного времени из относительного"""
        now = datetime.now()
        result = {"date": None, "time": None}
        
        try:
            if "завтра" in relative_time.lower():
                target_date = now + timedelta(days=1)
                result["date"] = target_date.strftime('%Y-%m-%d')
            elif "через" in relative_time.lower():
                if "час" in relative_time:
                    # Извлекаем количество часов
                    import re
                    hours = re.findall(r'\d+', relative_time)
                    if hours:
                        target_time = now + timedelta(hours=int(hours[0]))
                        result["date"] = target_time.strftime('%Y-%m-%d')
                        result["time"] = target_time.strftime('%H:%M')
                elif "день" in relative_time or "дня" in relative_time:
                    days = re.findall(r'\d+', relative_time)
                    if days:
                        target_date = now + timedelta(days=int(days[0]))
                        result["date"] = target_date.strftime('%Y-%m-%d')
        except Exception as e:
            logger.error(f"Ошибка вычисления времени: {e}")
            
        return result

    async def send_to_ios(self, reminder_data: dict) -> bool:
        """Отправка напоминания в iOS через Shortcuts webhook"""
        if not IOS_WEBHOOK_URL:
            logger.warning("iOS webhook URL не настроен")
            return False
            
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(IOS_WEBHOOK_URL, json=reminder_data) as response:
                    if response.status == 200:
                        logger.info("Напоминание успешно отправлено в iOS")
                        return True
                    else:
                        logger.error(f"Ошибка отправки в iOS: {response.status}")
                        return False
        except Exception as e:
            logger.error(f"Ошибка при отправке в iOS: {e}")
            return False

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка входящих сообщений"""
        user_message = update.message.text
        user_id = update.effective_user.id
        
        logger.info(f"Получено сообщение от {user_id}: {user_message}")
        
        # Показываем, что бот печатает
        await update.message.reply_text("🤖 Анализирую сообщение...")
        
        try:
            # Анализируем сообщение с помощью AI
            analysis = await self.analyze_message_with_ai(user_message)
            
            if not analysis.get("is_task", False):
                await update.message.reply_text(
                    "🤔 Я не смог определить это как задачу или напоминание.\n"
                    "Попробуйте сформулировать более четко, например:\n"
                    "• 'Завтра в 15:00 встреча с врачом'\n"
                    "• 'Через час принять лекарство'"
                )
                return
            
            # Формируем данные для iOS
            ios_data = {
                "title": analysis.get("title", user_message),
                "notes": analysis.get("description", ""),
                "date": analysis.get("date"),
                "time": analysis.get("time"),
                "priority": analysis.get("priority", "medium")
            }
            
            # Если есть относительное время, вычисляем абсолютное
            if analysis.get("relative_time"):
                abs_time = self.calculate_absolute_time(analysis["relative_time"])
                if abs_time["date"]:
                    ios_data["date"] = abs_time["date"]
                if abs_time["time"]:
                    ios_data["time"] = abs_time["time"]
            
            # Отправляем в iOS
            success = await self.send_to_ios(ios_data)
            
            if success:
                # Формируем подтверждение
                confirmation = f"✅ Напоминание создано!\n\n"
                confirmation += f"📝 **{ios_data['title']}**\n"
                
                if ios_data['date']:
                    confirmation += f"📅 Дата: {ios_data['date']}\n"
                if ios_data['time']:
                    confirmation += f"⏰ Время: {ios_data['time']}\n"
                    
                confirmation += f"🔥 Приоритет: {ios_data['priority']}"
                
                await update.message.reply_text(confirmation, parse_mode='Markdown')
            else:
                await update.message.reply_text(
                    "❌ Не удалось создать напоминание в iOS.\n"
                    "Проверьте настройки Shortcuts."
                )
            
        except Exception as e:
            logger.error(f"Ошибка обработки сообщения: {e}")
            await update.message.reply_text(
                "❌ Произошла ошибка при обработке сообщения.\n"
                "Попробуйте еще раз позже."
            )

    def run(self):
        """Запуск бота"""
        # Создаем приложение
        self.application = Application.builder().token(TELEGRAM_TOKEN).build()
        
        # Регистрируем обработчики
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
        
        # Запускаем бота
        logger.info("Бот запущен!")
        self.application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    # Проверяем наличие токенов
    if not TELEGRAM_TOKEN:
        logger.error("TELEGRAM_TOKEN не установлен!")
        exit(1)
        
    if not GEMINI_API_KEY:
        logger.error("GEMINI_API_KEY не установлен!")
        exit(1)
        
    # Запускаем бота
    bot = ReminderBot()
    bot.run()