import os
import asyncio
import logging
from datetime import datetime, timedelta
import json
import aiohttp
import re
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Конфигурация
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
YANDEX_TOKEN = os.getenv('YANDEX_TOKEN')

# Mapping категорий на ID календарей
CALENDAR_IDS = {
    'звонки с клиентами': '29717783',
    'методолог': '34555476',
    'обратная связь методологам': '34547674',
    'продуктовые задачи': '34547652',
    'рнп': '34552379',
    'жизнь': '34996389'
}

# Ключевые слова для определения категорий
CATEGORY_KEYWORDS = {
    'звонки с клиентами': ['звонок', 'звонить', 'созвон', 'разговор', 'клиент', 'переговоры'],
    'методолог': ['методолог', 'методология', 'метод'],
    'обратная связь методологам': ['обратная связь', 'фидбек', 'feedback', 'оценка'],
    'продуктовые задачи': ['продукт', 'фича', 'релиз', 'задача', 'разработка', 'техническ'],
    'рнп': ['рнп', 'р н п', 'руководитель', 'начальник'],
    'жизнь': ['личное', 'дом', 'семья', 'отдых', 'врач', 'покупки']
}

class YandexCalendarBot:
    def __init__(self):
        self.application = None
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        welcome_text = """Привет! Я бот для автоматического добавления событий в Яндекс.Календарь.

Примеры команд:
• "Звонок Петров в пятницу 18:00"
• "Встреча с методологом завтра в 14:00"
• "Продуктовая задача в понедельник 10:00"
• "РНП созвон в среду 16:30"
• "Обратная связь команде во вторник 15:00"

Я автоматически:
- Найду ближайшую дату
- Создам событие на 1 час
- Определю правильный календарь по ключевым словам

Команды:
/start - это сообщение
/categories - показать доступные категории
/calendars - показать все календари с ID"""
        await update.message.reply_text(welcome_text)

    async def categories_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        categories_text = """Доступные категории и ключевые слова:

1. **Звонки с клиентами** (ID: 29717783)
   Ключевые слова: звонок, созвон, клиент, переговоры

2. **Методолог** (ID: 34555476)  
   Ключевые слова: методолог, методология, метод

3. **Обратная связь методологам** (ID: 34547674)
   Ключевые слова: обратная связь, фидбек, оценка

4. **Продуктовые задачи** (ID: 34547652)
   Ключевые слова: продукт, фича, релиз, задача, разработка

5. **РНП** (ID: 34552379)
   Ключевые слова: рнп, руководитель, начальник

6. **Жизнь** (ID: 34996389)
   Ключевые слова: личное, дом, семья, отдых, врач, покупки

Просто используйте эти слова в сообщении для автоматической категоризации!"""
        await update.message.reply_text(categories_text, parse_mode='Markdown')

    async def calendars_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        calendars_text = "Настроенные календари:\n\n"
        for category, calendar_id in CALENDAR_IDS.items():
            calendars_text += f"• {category.title()}: {calendar_id}\n"
        await update.message.reply_text(calendars_text)

    def analyze_message(self, text: str) -> dict:
        """Анализ сообщения для извлечения события"""
        
        # Определяем категорию (по умолчанию - звонки с клиентами)
        category = 'звонки с клиентами'
        for cat, keywords in CATEGORY_KEYWORDS.items():
            for keyword in keywords:
                if keyword in text.lower():
                    category = cat
                    break
            if category != 'звонки с клиентами':  # Если нашли категорию, выходим
                break
        
        # Извлекаем время
        now = datetime.now()
        event_date = None
        event_time = None
        
        # Дни недели
        weekdays = {
            'понедельник': 0, 'вторник': 1, 'среда': 2, 'четверг': 3,
            'пятница': 4, 'суббота': 5, 'воскресенье': 6
        }
        
        # Относительные даты
        if 'завтра' in text.lower():
            event_date = now + timedelta(days=1)
        elif 'послезавтра' in text.lower():
            event_date = now + timedelta(days=2)
        elif 'сегодня' in text.lower():
            event_date = now
        
        # Поиск дня недели (включая "в пятницу")
        for day_name, day_num in weekdays.items():
            if day_name in text.lower() or f"в {day_name}" in text.lower():
                days_ahead = day_num - now.weekday()
                if days_ahead <= 0:  # Если день уже прошел, берем следующую неделю
                    days_ahead += 7
                event_date = now + timedelta(days=days_ahead)
                break
        
        # Извлекаем время
        time_patterns = [
            r'(\d{1,2}):(\d{2})',  # 18:00
            r'в (\d{1,2}):(\d{2})',  # в 18:00
            r'(\d{1,2})\s*(\d{2})'  # 18 00
        ]
        
        for pattern in time_patterns:
            time_match = re.search(pattern, text)
            if time_match:
                hour = int(time_match.group(1))
                minute = int(time_match.group(2))
                if 0 <= hour <= 23 and 0 <= minute <= 59:
                    event_time = f"{hour:02d}:{minute:02d}"
                    break
        
        # Если время не найдено, ставим время по умолчанию
        if not event_time and event_date:
            event_time = "10:00"  # По умолчанию 10:00
        
        # Генерируем заголовок события (убираем время и день недели)
        title = text
        # Убираем временные выражения
        title = re.sub(r'\b(в\s+)?(\d{1,2}):(\d{2})\b', '', title)
        title = re.sub(r'\b(завтра|послезавтра|сегодня|понедельник|вторник|среда|четверг|пятница|суббота|воскресенье)\b', '', title, flags=re.IGNORECASE)
        title = re.sub(r'\s+', ' ', title).strip()
        
        return {
            'title': title,
            'category': category,
            'calendar_id': CALENDAR_IDS[category],
            'date': event_date,
            'time': event_time,
            'original_text': text
        }

    async def test_api_connection(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Тест различных API endpoint'ов"""
        await update.message.reply_text("Тестирую подключение к Яндекс API...")
        
        headers = {
            'Authorization': f'OAuth {YANDEX_TOKEN}',
            'Content-Type': 'application/json'
        }
        
        # Различные endpoints для тестирования
        test_endpoints = [
            "https://calendar.yandex.ru/api/v1/events",
            "https://calendar.yandex.ru/api/v2/events", 
            "https://api.calendar.yandex.ru/api/v1/events",
            "https://calendar.yandex.net/api/v1/events",
        ]
        
        results = []
        
        for endpoint in test_endpoints:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(endpoint, headers=headers) as response:
                        status = response.status
                        results.append(f"• {endpoint}: {status}")
                        if status == 200:
                            results.append(f"  ✅ Подключение работает!")
            except Exception as e:
                results.append(f"• {endpoint}: Ошибка - {str(e)[:50]}")
        
        await update.message.reply_text("Результаты тестирования:\n" + "\n".join(results))

    async def create_yandex_event(self, event_data: dict) -> dict:
        """Создание события в Яндекс.Календаре с подробным логированием"""
        
        event_date = event_data['date']
        event_time = event_data['time']
        calendar_id = event_data['calendar_id']
        
        if not event_date or not event_time:
            return {"success": False, "error": "Нет даты или времени"}
        
        # Создаем datetime для начала события
        time_parts = event_time.split(':')
        start_datetime = event_date.replace(
            hour=int(time_parts[0]),
            minute=int(time_parts[1]),
            second=0,
            microsecond=0
        )
        
        # Конец события (через 1 час)
        end_datetime = start_datetime + timedelta(hours=1)
        
        # Различные форматы payload для разных API
        payloads = [
            {
                'name': event_data['title'],
                'startTs': start_datetime.isoformat(),
                'endTs': end_datetime.isoformat(),
                'layerId': calendar_id
            },
            {
                'title': event_data['title'],
                'start': start_datetime.isoformat(),
                'end': end_datetime.isoformat(),
                'calendar_id': calendar_id
            },
            {
                'summary': event_data['title'],
                'dtstart': start_datetime.strftime('%Y%m%dT%H%M%S'),
                'dtend': end_datetime.strftime('%Y%m%dT%H%M%S'),
                'calendar': calendar_id
            }
        ]
        
        # Различные endpoints
        endpoints = [
            f"https://calendar.yandex.ru/api/v1/events",
            f"https://calendar.yandex.ru/api/v2/events", 
            f"https://api.calendar.yandex.ru/api/v1/events"
        ]
        
        headers = {
            'Authorization': f'OAuth {YANDEX_TOKEN}',
            'Content-Type': 'application/json',
            'X-Requested-With': 'XMLHttpRequest'
        }
        
        # Пробуем все комбинации endpoint + payload
        for i, endpoint in enumerate(endpoints):
            for j, payload in enumerate(payloads):
                try:
                    logger.info(f"Пробуем endpoint {i+1}/{len(endpoints)}, payload {j+1}/{len(payloads)}")
                    logger.info(f"URL: {endpoint}")
                    logger.info(f"Payload: {payload}")
                    
                    async with aiohttp.ClientSession() as session:
                        async with session.post(endpoint, headers=headers, json=payload) as response:
                            status = response.status
                            response_text = await response.text()
                            
                            logger.info(f"Ответ: {status} - {response_text[:200]}")
                            
                            if status in [200, 201]:
                                return {"success": True, "response": response_text}
                            elif status == 401:
                                return {"success": False, "error": "Проблема с токеном авторизации"}
                            elif status == 403:
                                return {"success": False, "error": "Нет прав доступа к календарю"}
                            elif status == 404:
                                return {"success": False, "error": "API endpoint не найден"}
                            else:
                                continue  # Пробуем следующую комбинацию
                                
                except Exception as e:
                    logger.info(f"Ошибка: {str(e)}")
                    continue
        
        return {"success": False, "error": "Все API методы не работают"}

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка входящих сообщений"""
        user_message = update.message.text
        user_id = update.effective_user.id
        
        logger.info(f"Получено сообщение от {user_id}: {user_message}")
        
        processing_msg = await update.message.reply_text("Анализирую сообщение и создаю событие...")
        
        try:
            # Анализируем сообщение
            event_data = self.analyze_message(user_message)
            
            if not event_data['date']:
                await processing_msg.edit_text(
                    "Не удалось определить дату.\n"
                    "Попробуйте указать день: 'завтра', 'в пятницу', 'сегодня'"
                )
                return
            
            # Показываем что было проанализировано
            analysis_text = f"Проанализировал ваш запрос:\n\n"
            analysis_text += f"📋 Событие: {event_data['title']}\n"
            analysis_text += f"📅 Дата: {event_data['date'].strftime('%d.%m.%Y')}\n"
            analysis_text += f"⏰ Время: {event_data['time']}\n"
            analysis_text += f"📂 Календарь: {event_data['category']}\n"
            analysis_text += f"🔢 ID календаря: {event_data['calendar_id']}\n\n"
            analysis_text += "Создаю событие..."
            
            await processing_msg.edit_text(analysis_text)
            
            # Создаем событие
            result = await self.create_yandex_event(event_data)
            
            if result["success"]:
                final_text = f"✅ Событие успешно создано!\n\n"
                final_text += f"📋 {event_data['title']}\n"
                final_text += f"📅 {event_data['date'].strftime('%d.%m.%Y')}\n"
                final_text += f"⏰ {event_data['time']} - {(datetime.strptime(event_data['time'], '%H:%M') + timedelta(hours=1)).strftime('%H:%M')}\n"
                final_text += f"📂 Календарь: {event_data['category']}\n\n"
                final_text += "Событие добавлено в ваш Яндекс.Календарь!"
                
                await processing_msg.edit_text(final_text)
            else:
                error_text = f"❌ Не удалось создать событие в календаре.\n\n"
                error_text += f"Проанализированные данные:\n"
                error_text += f"📋 {event_data['title']}\n"
                error_text += f"📅 {event_data['date'].strftime('%d.%m.%Y')}\n"
                error_text += f"⏰ {event_data['time']}\n"
                error_text += f"📂 Календарь: {event_data['category']}\n\n"
                error_text += f"Ошибка API: {result['error']}\n"
                error_text += f"Используйте /test для диагностики API"
                
                await processing_msg.edit_text(error_text)
                
        except Exception as e:
            logger.error(f"Ошибка обработки сообщения: {e}")
            await processing_msg.edit_text(f"❌ Произошла ошибка: {str(e)}")

    def run(self):
        """Запуск бота"""
        self.application = Application.builder().token(TELEGRAM_TOKEN).build()
        
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("categories", self.categories_command))
        self.application.add_handler(CommandHandler("calendars", self.calendars_command))
        self.application.add_handler(CommandHandler("test", self.test_api_connection))
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
        
        logger.info("Яндекс.Календарь бот запущен!")
        self.application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    if not TELEGRAM_TOKEN:
        logger.error("TELEGRAM_TOKEN не установлен!")
        exit(1)
        
    if not YANDEX_TOKEN:
        logger.error("YANDEX_TOKEN не установлен!")
        exit(1)
        
    bot = YandexCalendarBot()
    bot.run()
