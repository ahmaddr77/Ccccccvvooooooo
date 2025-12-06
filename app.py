import os
import logging
import asyncio
import io
import time
from threading import Thread
from flask import Flask
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import google.generativeai as genai
from pypdf import PdfReader, PdfWriter

# ==========================================
# ⚙️ إعدادات النظام والمفاتيح
# ==========================================
# ⚠️ تنبيه: يفضل وضع المفاتيح في Environment Variables في ريندر للأمان، لكن تم وضعها هنا للتسهيل كما طلبت
ADMIN_ID = 7584618344
ACCESS_PASSWORD = r"Ahsghsshwkwshzbzbzbssnan282737337!#??$!*?@)$-$-+#!@@??@;#."
TELEGRAM_TOKEN = "8343659359:AAHa2vNnm6nx7I-OHvgYLtB9q6s0P-ULqg0"
GEMINI_API_KEY = "AIzaSyCSZPs0yYcL6Rqt4uf9mdjezuC98pAS6TM"

# إعداد الويب سيرفر الوهمي لإرضاء Render
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running fast and furious! 🚀"

def run_web_server():
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)

# ==========================================
# 📝 التهيئة
# ==========================================
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# تهيئة Gemini
try:
    genai.configure(api_key=GEMINI_API_KEY)
    # نستخدم موديل فلاش للسرعة القصوى
    model = genai.GenerativeModel(
        model_name="gemini-2.0-flash",
        generation_config={"temperature": 0.1, "top_p": 1, "top_k": 1}
    )
except Exception as e:
    logger.error(f"❌ Gemini Error: {e}")

# ==========================================
# 🧠 البرومبت (فارغ كما طلبت)
# ==========================================
# 🛑 هام: قم بوضع البرومبت الخاص بك هنا بين علامات التنصيص
EXTRACTION_PROMPT = """
"""

if not EXTRACTION_PROMPT.strip():
    logger.warning("⚠️ البرومبت فارغ! لن يعمل الاستخراج بشكل صحيح حتى تقوم بتعبئته.")

# ==========================================
# 🔄 نظام الطابور (Queue System)
# ==========================================
file_queue = asyncio.Queue()
processing_active = False

async def worker(context: ContextTypes.DEFAULT_TYPE):
    """العامل الذي يعمل في الخلفية لمعالجة الطابور"""
    global processing_active
    logger.info("🚀 Worker started waiting for tasks...")
    
    while True:
        # انتظر ملفاً من الطابور
        task_data = await file_queue.get()
        processing_active = True
        
        chat_id = task_data['chat_id']
        file_path = task_data['file_path']
        original_name = task_data['file_name']
        message_id = task_data['message_id']

        try:
            # إعلام المستخدم ببدء المعالجة لهذا الملف
            status_msg = await context.bot.send_message(
                chat_id=chat_id, 
                text=f"⚡ **بدأ تحليل الملف:** {original_name}\n⏳ جاري المعالجة بأقصى سرعة...",
                reply_to_message_id=message_id
            )

            # معالجة الملف
            extracted_text = await process_pdf_fast(file_path)

            if extracted_text.strip():
                # إرسال النتيجة كملف نصي
                output_filename = f"Extracted_{original_name}.txt"
                with io.BytesIO(extracted_text.encode('utf-8')) as f:
                    f.name = output_filename
                    await context.bot.send_document(
                        chat_id=chat_id,
                        document=f,
                        caption=f"✅ **تم الانتهاء:** {original_name}\n📄 تفضل ملف الاستخراج.",
                        reply_to_message_id=message_id
                    )
            else:
                await context.bot.send_message(chat_id, "⚠️ لم يتم استخراج أي نصوص. تحقق من البرومبت أو الملف.", reply_to_message_id=message_id)

            # حذف رسالة الحالة المؤقتة
            try:
                await context.bot.delete_message(chat_id, status_msg.message_id)
            except:
                pass

        except Exception as e:
            logger.error(f"Error processing file: {e}")
            await context.bot.send_message(chat_id, f"❌ حدث خطأ أثناء معالجة الملف: {original_name}\nالخطأ: {str(e)}")
        
        finally:
            # تنظيف الملفات المؤقتة
            if os.path.exists(file_path):
                os.remove(file_path)
            
            # إعلام الطابور بانتهاء المهمة
            file_queue.task_done()
            
            # التحقق مما إذا كان هناك ملفات متبقية
            q_size = file_queue.qsize()
            if q_size > 0:
                await context.bot.send_message(chat_id, f"📥 **المتبقي في الطابور:** {q_size} ملف(ات). جاري الانتقال للتالي...")
            else:
                processing_active = False

async def process_pdf_fast(pdf_path):
    """دالة المعالجة السريعة جداً باستخدام التوازي"""
    reader = PdfReader(pdf_path)
    total_pages = len(reader.pages)
    
    # تقسيم الملف إلى قطع (Chunks)
    CHUNK_SIZE = 10  # عدد الصفحات لكل قطعة (تم زيادته لأن Gemini 2.0 يتحمل سياقاً كبيراً)
    tasks = []
    
    # تحضير المهام
    for i in range(0, total_pages, CHUNK_SIZE):
        chunk_writer = PdfWriter()
        end_page = min(i + CHUNK_SIZE, total_pages)
        for page_num in range(i, end_page):
            chunk_writer.add_page(reader.pages[page_num])
        
        # حفظ القطعة في الذاكرة (BytesIO) لتوفير وقت الكتابة على القرص
        chunk_buffer = io.BytesIO()
        chunk_writer.write(chunk_buffer)
        chunk_buffer.seek(0)
        
        # إضافة المهمة للقائمة
        tasks.append(analyze_chunk_concurrently(chunk_buffer, f"Pages {i+1}-{end_page}"))

    # 🔥 تشغيل جميع المهام في وقت واحد (Parallel Execution)
    results = await asyncio.gather(*tasks)
    
    # تجميع النتائج بالترتيب
    full_text = "\n".join([res for res in results if res])
    return full_text

async def analyze_chunk_concurrently(file_stream, chunk_name):
    """إرسال القطعة لـ Gemini وانتظار الرد (مصمم للتوازي)"""
    temp_filename = f"temp_chunk_{time.time()}_{chunk_name.replace(' ', '_')}.pdf"
    
    try:
        # نحتاج لحفظ الملف مؤقتاً لأن Gemini API upload يحتاج مسار ملف
        with open(temp_filename, "wb") as f:
            f.write(file_stream.getbuffer())

        # رفع الملف لـ Gemini
        u_file = await asyncio.to_thread(genai.upload_file, temp_filename, mime_type="application/pdf")
        
        # انتظار المعالجة من طرف Google
        while u_file.state.name == "PROCESSING":
            await asyncio.sleep(0.5)
            u_file = genai.get_file(u_file.name)

        # الطلب من الموديل
        prompt = EXTRACTION_PROMPT
        if not prompt:
            return "Error: Prompt is empty."

        response = await asyncio.to_thread(
            model.generate_content,
            [u_file, prompt],
            request_options={'timeout': 600}
        )
        
        # حذف الملف من سيرفرات جوجل لتوفير المساحة
        await asyncio.to_thread(u_file.delete)
        
        return response.text

    except Exception as e:
        logger.error(f"Error in chunk {chunk_name}: {e}")
        return f"\n[Error processing {chunk_name}]\n"
    finally:
        if os.path.exists(temp_filename):
            os.remove(temp_filename)

# ==========================================
# 🎮 التعامل مع المستخدم
# ==========================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 **أهلاً بك في بوت الاستخراج السريع!** 🚀\n\n"
        "📥 **نظام العمل:**\n"
        "1. أرسل ملفات PDF (يمكنك إرسال عدة ملفات دفعة واحدة).\n"
        "2. سيقوم البوت بترتيبها في طابور.\n"
        "3. سيتم استخراج البيانات وإرسالها لك كملف نصي.\n"
        "4. **لا تقلق:** البوت يعمل بنظام التوازي الداخلي للسرعة القصوى.\n\n"
        "🔒 أرسل كلمة المرور للبدء."
    )
    return 1

async def check_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text.strip() == ACCESS_PASSWORD:
        context.user_data['authorized'] = True
        await update.message.reply_text("🔓 **تم التفعيل بنجاح!**\n\n🚀 أرسل ملفات PDF الآن وسأقوم بطحنها!")
    else:
        await update.message.reply_text("❌ كلمة المرور خاطئة.")

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # التحقق من الصلاحية
    if not context.user_data.get('authorized'):
        await update.message.reply_text("🔒 يرجى إرسال كلمة المرور أولاً.")
        return

    doc = update.message.document
    if not doc.mime_type or 'pdf' not in doc.mime_type.lower():
        await update.message.reply_text("⚠️ يرجى إرسال ملفات PDF فقط.")
        return

    # تحميل الملف
    file = await doc.get_file()
    file_name = doc.file_name
    local_path = f"download_{doc.file_unique_id}.pdf"
    await file.download_to_drive(local_path)

    # إضافة للطابور
    queue_item = {
        'chat_id': update.effective_chat.id,
        'file_path': local_path,
        'file_name': file_name,
        'message_id': update.message.message_id
    }
    
    await file_queue.put(queue_item)
    q_size = file_queue.qsize()
    
    msg = f"✅ **تمت إضافة الملف للطابور:** {file_name}"
    if q_size > 1:
        msg += f"\n🔢 ترتيبه في الانتظار: {q_size}"
    
    await update.message.reply_text(msg)

# ==========================================
# 🚀 التشغيل الرئيسي
# ==========================================
def main():
    # تشغيل سيرفر Flask في Thread منفصل لكي لا يوقف البوت
    server_thread = Thread(target=run_web_server)
    server_thread.daemon = True
    server_thread.start()

    # إعداد البوت
    if not os.path.exists('temp'):
        os.makedirs('temp')

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    # تعريف المعالجات
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, check_password)) # استقبال الباسورد
    app.add_handler(MessageHandler(filters.Document.PDF, handle_document)) # استقبال الملفات

    # إضافة وظيفة الطابور لتعمل مع بدء البوت
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    app.job_queue.run_once(worker, when=1) # تشغيل العامل فوراً

    print("🚀 Bot Started on Render with Queue System...")
    app.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()