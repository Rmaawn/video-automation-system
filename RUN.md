# 🚀 راهنمای اجرا

## ۱. نصب
```
pip install -r requirements.txt
```

## ۲. تنظیم HeyGen
```
copy .env.example .env
```
فایل `.env` رو باز کن و این سه تا رو پر کن:
```
HEYGEN_API_KEY=کلید_خودت
HEYGEN_AVATAR_ID=آواتار_خودت
HEYGEN_VOICE_ID=صدای_خودت
```
> از پنل HeyGen → Settings → API

## ۳. گذاشتن محتوای کتاب
فقط **یک فایل**: `data/content/book.json`

ساختارش:
```json
{
  "book_id": "my_book",
  "title": "اسم کتاب",
  "language": "fa",
  "chapters": [
    {
      "chapter": "chapter_1",
      "sections": [
        {"section": "1", "text": "متن بخش اول..."},
        {"section": "2", "text": "متن بخش دوم..."}
      ]
    }
  ]
}
```

هر بخش (`section`) = یک ویدیو.

## ۴. دستورها

| دستور | کار |
|---|---|
| `python main.py load` | لود کتاب از book.json |
| `python main.py` | ساخت **یک** ویدیو |
| `python main.py batch` | ساخت **همه** ویدیوهای باقی‌مونده |
| `python main.py status` | وضعیت سیستم |

## 📌 جریان کار

هر بار:
1. محتواتو بزن تو `data/content/book.json`
2. `python main.py load` (قبلی‌ها رو خودکار رد می‌کنه)
3. `python main.py` → یک ویدیو ساخته میشه
4. ویدیو ذخیره: `output/videos/`

سیستم خودش می‌دونه تا کجا اومده. هر بار `load` بزنی فقط بخش‌های جدید رو اضافه می‌کنه.

## ⚡ نکات

- `HEYGEN_TEST_MODE=true` → تست بدون کسر اعتبار
- لاگ: `output/logs/video_automation.log`
- دیتابیس: `output/video_automation.db`
- هر `content.retry_count` تا ۳ بار retry می‌کنه
