# استخدام نسخة بايثون رسمية وخفيفة
FROM python:3.10-slim

# تثبيت أداة ffmpeg وتحديث مستودعات النظام
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# تحديد مجلد العمل داخل الحاوية
WORKDIR /app

# نسخ ملف الطلبات وتثبيت مكتبات البايثون
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# نسخ باقي ملفات البوت إلى الحاوية
COPY . .

# أمر تشغيل البوت الأساسي (تأكد من تعديل اسم الملف إذا كان مختلفاً عن app.py)
CMD ["python", "app.py"]
