# WP0 — Persian quality review (blind)

For the owner (native Persian speaker). Candidate names are hidden; the letters are shuffled **per item**, so A in one item is not necessarily A in another. The mapping is in `WP0_persian_review_key.md`; please score before opening it.

Score each output 1–5 for **fluency** (F), **accuracy / faithfulness** (A) and **naturalness** (N). For small-talk items, A = appropriateness of the reply.

Instruction prompts used (identical for all candidates) are listed in `WP0_report.md` §6.

**Note:** only 1 candidate produced Persian outputs; not run: C1 (gemma-4-31b-it), C3 (google/gemma-4-31b-it:free) (see `WP0_report.md` §6/§7). Labels are still hidden, but with a single candidate this is an absolute rating, not a comparison.

## 1. `t_en_fa_casual` (translate_to_fa)

**Source:**

> Hey! Sorry I missed your call earlier, I was stuck in a meeting. Want to grab coffee this weekend? Let me know what works for you.

**A:**

> سلام! متأسفم که تماس قبلی‌ات را جواب ندادم، در یک جلسه گیر کرده بودم. دوست داری این هفته قهوه بخوریم؟ بگو چه زمانی برایت مناسب است.

| Output | F (1–5) | A (1–5) | N (1–5) | Notes |
|---|---|---|---|---|
| A | | | | |

## 2. `t_en_fa_technical` (translate_to_fa)

**Source:**

> Cloud computing lets organizations rent computing resources such as servers, storage and databases on demand instead of buying and maintaining their own hardware. Providers offer these resources through three main service models: Infrastructure as a Service (IaaS), Platform as a Service (PaaS) and Software as a Service (SaaS). Autoscaling allows an application to add or remove virtual machines automatically as traffic changes, so customers pay only for the capacity they actually use.

**A:**

> حساب ابری به سازمان‌ها امکان می‌دهد منابع محاسباتی مانند سرورها، حافظه و پایگاه‌های داده را به‌صورت درخواستی اجاره کنند، به‌جای خرید و نگهداری سخت‌افزار اختصاصی. ارائه‌دهندگان این منابع را از طریق سه مدل اصلی خدمات ارائه می‌دهند: زیرساخت به‌عنوان‌خدمت (IaaS)، پلتفرم به‌عنوان‌خدمت (PaaS) و نرم‌افزار به‌عنوان‌خدمت (SaaS). مقیاس‌بندی خودکار به یک برنامه امکان می‌دهد با تغییرات ترافیک، به‌طور خودکار ماشین‌های مجازی اضافه یا حذف کند، تا مشتریان تنها برای ظرفیتی که واقعاً استفاده می‌کنند، پرداخت کنند.

| Output | F (1–5) | A (1–5) | N (1–5) | Notes |
|---|---|---|---|---|
| A | | | | |

## 3. `t_en_fa_entities` (translate_to_fa)

**Source:**

> On March 14, 2025, Dr. Sarah Thompson presented the results of a study involving 1,250 participants at a conference in Vienna.

**A:**

> در ۱۴ مارس ۲۰۲۵، دکتر سارا تامپسون نتایج پژوهشی شامل ۱۲۵۰ شرکت‌کننده را در کنفرانسی در وین ارائه کرد.

| Output | F (1–5) | A (1–5) | N (1–5) | Notes |
|---|---|---|---|---|
| A | | | | |

## 4. `t_fa_en_formal` (translate_to_en)

**Source:**

> بدین‌وسیله به اطلاع می‌رساند که جلسه‌ی هیئت‌مدیره، که پیش‌تر برای روز دوشنبه برنامه‌ریزی شده بود، به دلیل شرایط پیش‌بینی‌نشده به هفته‌ی آینده موکول شده است. از همه‌ی اعضای محترم درخواست می‌شود گزارش‌های خود را حداکثر تا پایان روز پنجشنبه به دبیرخانه ارسال کنند.

**A:**

> This is to inform you that the board meeting, previously scheduled for Monday, has been postponed to next week due to unforeseen circumstances. All respected members are requested to submit their reports to the secretariat by the end of the day on Thursday.

| Output | F (1–5) | A (1–5) | N (1–5) | Notes |
|---|---|---|---|---|
| A | | | | |

## 5. `t_fa_en_colloquial` (translate_to_en)

**Source:**

> بابا ول کن دیگه، دیروز کلی منتظرت موندم ولی آخرش نیومدی، حداقل یه زنگ می‌زدی!

**A:**

> Dad, stop ignoring me. I waited for you all day yesterday, but you didn't show up. At least you could have called!

| Output | F (1–5) | A (1–5) | N (1–5) | Notes |
|---|---|---|---|---|
| A | | | | |

## 6. `s_fa_water` (summarize_fa)

**Source:**

> ایران در سال‌های اخیر با یکی از جدی‌ترین بحران‌های کم‌آبی در تاریخ خود روبه‌رو شده است. بخش بزرگی از منابع آب شیرین کشور، یعنی نزدیک به نود درصد، در بخش کشاورزی مصرف می‌شود و بیشتر این مصرف با روش‌های سنتی آبیاری غرقابی انجام می‌گیرد که بازده پایینی دارند. برداشت بی‌رویه از آب‌های زیرزمینی باعث شده است سطح سفره‌های آب در بسیاری از دشت‌ها هر سال پایین‌تر برود و در برخی مناطق، زمین دچار فرونشست شود. کارشناسان می‌گویند گسترش آبیاری قطره‌ای، تغییر الگوی کشت به سمت محصولاتی که آب کمتری نیاز دارند و قیمت‌گذاری واقعی آب می‌تواند به کاهش مصرف کمک کند. در شهرها نیز استفاده از شیرآلات کم‌مصرف، تعمیر به‌موقع لوله‌های فرسوده و بازچرخانی پساب برای آبیاری فضای سبز از راهکارهای مؤثر به شمار می‌روند. با این حال، بسیاری از پژوهشگران تأکید می‌کنند که بدون همکاری مردم و برنامه‌ریزی بلندمدت دولت، هیچ‌یک از این راهکارها به‌تنهایی نمی‌تواند بحران را مهار کند.

**A:**

> ایران با بحران جدی کم‌آبی مواجه است که عمدتاً ناشی از مصرف بالای آب در بخش کشاورزی با روش‌های سنتی و برداشت بی‌رویه از آب‌های زیرزمینی است. راهکارهای پیشنهادی شامل گسترش آبیاری قطره‌ای، تغییر الگوی کشت و مدیریت مصرف شهری هستند، اما کارشناسان تأکید دارند که بدون همکاری مردم و برنامه‌ریزی بلندمدت دولت، مهار این بحران ممکن نخواهد بود.

| Output | F (1–5) | A (1–5) | N (1–5) | Notes |
|---|---|---|---|---|
| A | | | | |

## 7. `s_fa_sleep` (summarize_fa)

**Source:**

> خواب کافی یکی از پایه‌های اصلی سلامت جسم و روان است، اما در زندگی پرمشغله‌ی امروز اغلب نادیده گرفته می‌شود. پژوهش‌ها نشان می‌دهند که بزرگسالان برای عملکرد مطلوب به هفت تا نه ساعت خواب در شبانه‌روز نیاز دارند. کم‌خوابی مزمن با افزایش خطر بیماری‌هایی مانند دیابت نوع دو، فشار خون بالا و افسردگی همراه است و توانایی تمرکز، یادگیری و تصمیم‌گیری را نیز کاهش می‌دهد. یکی از عوامل مهم بی‌خوابی، استفاده از تلفن همراه و رایانه پیش از خواب است؛ نور آبی این دستگاه‌ها ترشح ملاتونین را، که هورمونی برای تنظیم چرخه‌ی خواب است، به تأخیر می‌اندازد. متخصصان توصیه می‌کنند هر شب در ساعت مشخصی به رختخواب بروید، اتاق خواب را تاریک، خنک و آرام نگه دارید و از نوشیدن قهوه و چای در ساعات پایانی روز پرهیز کنید. ورزش منظم در طول روز نیز به خواب عمیق‌تر کمک می‌کند، به شرط آنکه درست پیش از خواب انجام نشود.

**A:**

> خواب کافی برای سلامت جسم و روان ضروری است و کمبود آن با افزایش خطر بیماری‌هایی مانند دیابت و افسردگی همراه است. عواملی مانند نور آبی دستگاه‌های الکترونیکی و مصرف کافئین در شب می‌توانند کیفیت خواب را مختل کنند. برای بهبود خواب، رعایت زمان‌بندی منظم، ایجاد محیط آرام و تاریک در اتاق خواب و ورزش منظم در طول روز توصیه می‌شود.

| Output | F (1–5) | A (1–5) | N (1–5) | Notes |
|---|---|---|---|---|
| A | | | | |

## 8. `c_fa_mood` (chat)

**Source:**

> سلام، امروز حالم زیاد خوب نیست

**A:**

> متأسفم که این را می‌شنوم. امیدوارم هرچه زودتر حال‌تان بهتر شود.

| Output | F (1–5) | A (1–5) | N (1–5) | Notes |
|---|---|---|---|---|
| A | | | | |

## 9. `c_fa_joke` (chat)

**Source:**

> یه جوک بامزه بگو

**A:**

> یه روز یه گربه به یه سگ گفت: «می‌دونی چرا ما همیشه با هم دعوا می‌کنیم؟»
> سگ پرسید: «چرا؟»
> گربه جواب داد: «چون تو همیشه فکر می‌کنی من یه سگِ بدجنس‌تر از خودتم!»

| Output | F (1–5) | A (1–5) | N (1–5) | Notes |
|---|---|---|---|---|
| A | | | | |
