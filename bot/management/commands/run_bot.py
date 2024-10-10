# bot/management/commands/run_bot.py

from django.core.management.base import BaseCommand
from django.conf import settings
import logging
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from openai import AsyncOpenAI

aclient = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
import os
import cv2
import numpy as np
from PIL import Image
import pytesseract
import re

# إعداد التسجيل
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# إعداد OpenAI

class Command(BaseCommand):
    help = 'تشغيل بوت تيليجرام'

    def handle(self, *args, **kwargs):
        application = ApplicationBuilder().token(settings.TELEGRAM_TOKEN).build()

        # أوامر البوت
        application.add_handler(CommandHandler('start', self.start))
        application.add_handler(CommandHandler('help', self.help_command))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
        application.add_handler(MessageHandler(filters.PHOTO, self.handle_photo))

        # بدء البوت
        application.run_polling()

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text('مرحبًا! أرسل لي صورة الشارت أو اطرح سؤالك حول التداول.')

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text('أرسل صورة الشارت للحصول على تحليل، أو اسألني أي سؤال عن التداول.')

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_message = update.message.text
        response = await self.get_openai_response(user_message)
        await update.message.reply_text(response)

    async def handle_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        logger.info('تم استقبال صورة من المستخدم.')
        try:
            photo_file = await update.message.photo[-1].get_file()
            os.makedirs('media', exist_ok=True)
            photo_path = os.path.join('media', f'{update.message.chat_id}.jpg')
            await photo_file.download_to_drive(photo_path)
            logger.info(f'تم تنزيل الصورة إلى {photo_path}')

            # معالجة الصورة
            chart_description = self.analyze_image(photo_path)
            prompt = f'قدم تحليلًا فنيًا للشارت التالي:\n{chart_description}'
            response = await self.get_openai_response(prompt)

            await update.message.reply_text(response)
        except Exception as e:
            logger.error(f'خطأ في handle_photo: {e}')
            await update.message.reply_text('عذرًا، لا يمكنني معالجة صورتك.')

    def analyze_image(self, image_path):
        try:
            # قراءة الصورة باستخدام OpenCV
            img = cv2.imread(image_path)

            # التحقق من أن الصورة تم تحميلها بنجاح
            if img is None:
                logger.error('الصورة لم يتم تحميلها بشكل صحيح.')
                return 'لا يمكن تحليل الشارت.'

            # تحويل الصورة إلى تدرج الرمادي
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

            # تطبيق الكشف عن الحواف
            edges = cv2.Canny(gray, threshold1=50, threshold2=150, apertureSize=3)

            # الكشف عن الخطوط
            lines = cv2.HoughLinesP(edges, 1, np.pi/180, threshold=50, minLineLength=50, maxLineGap=10)

            # تحليل الشموع اليابانية (كمثال بسيط)
            # هذا جزء معقد ويتطلب خوارزميات متقدمة، لكن سأقدم مثالًا مبسطًا

            # الكشف عن المستطيلات (التي قد تمثل الشموع)
            contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            candlesticks = [cnt for cnt in contours if cv2.contourArea(cnt) > 100]

            # تحديد عدد الشموع الصعودية والهبوطية بناءً على الشكل
            bullish = 0
            bearish = 0

            for cnt in candlesticks:
                x, y, w, h = cv2.boundingRect(cnt)
                aspect_ratio = float(w)/h
                if aspect_ratio > 0.2:  # معيار بسيط للتمييز
                    bullish += 1
                else:
                    bearish += 1

            # استخدام OCR لاستخراج النصوص والمعلومات من الشارت
            # تحويل الصورة إلى RGB لأن pytesseract يعمل بشكل أفضل مع RGB
            img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            pil_img = Image.fromarray(img_rgb)
            text = pytesseract.image_to_string(pil_img, lang='eng')  # استخدم 'ara' للغة العربية إذا لزم الأمر

            # استخراج المؤشرات الفنية من النص باستخدام التعبيرات النمطية
            indicators = self.extract_indicators(text)

            # إعداد وصف مفصل بناءً على الشموع والمؤشرات
            description = f'تم اكتشاف {len(candlesticks)} شمعة. الشموع الصعودية: {bullish}, الشموع الهبوطية: {bearish}.\n'

            if indicators:
                description += 'المؤشرات الفنية المستخرجة:\n'
                for key, value in indicators.items():
                    description += f'{key}: {value}\n'
            else:
                description += 'لم يتم استخراج مؤشرات فنية من الشارت.'

            # إضافة تحليل الاتجاه بناءً على الشموع
            if bullish > bearish:
                trend = 'اتجاه صعودي'
            elif bearish > bullish:
                trend = 'اتجاه هبوطي'
            else:
                trend = 'نطاق عرضي'

            description += f'\nالاتجاه العام: {trend}.'

            return description

        except Exception as e:
            logger.error(f'خطأ في analyze_image: {e}')
            return 'لا يمكن تحليل الشارت.'

    def extract_indicators(self, text):
        # دالة لاستخراج المؤشرات والقيم باستخدام التعبيرات النمطية (Regex)
        indicators = {}
        patterns = {
            'MA14': r'MA14[:\s]+(\d+\.?\d*)',
            'MA200': r'MA200[:\s]+(\d+\.?\d*)',
            'RSI': r'RSI[:\s]+(\d+\.?\d*)',
            # أضف المزيد من المؤشرات هنا حسب الحاجة
        }
        for key, pattern in patterns.items():
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                indicators[key] = match.group(1)
        return indicators

    async def get_openai_response(self, prompt):
        try:
            response = await aclient.chat.completions.create(model='gpt-3.5-turbo',  # استخدم 'gpt-4' إذا كان لديك حق الوصول
            messages=[
                {"role": "system", "content": """
أنت مساعد تداول مالي خبير في التحليل الفني. عندما يتم تزويدك بوصف شارت أو بيانات محدودة، قم بتقديم تحليل فني مفصل باستخدام أفضل تقدير ممكن بناءً على المعلومات المتاحة. استخدم خبرتك لتفسير الأنماط المحتملة وقدم توصيات مبنية على التحليل.
                    """},
                {"role": "user", "content": prompt}
            ],
            max_tokens=1000,
            temperature=0.7)
            content = response.choices[0].message.content.strip()
            return content
        except Exception as e:
            logger.error(f'خطأ في OpenAI API: {e}')
            return 'عذرًا، لا يمكنني معالجة طلبك حاليًا.'
