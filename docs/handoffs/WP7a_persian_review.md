# WP7a — blind A/B Persian review (prompt v1 vs v2)

For each sample, two outputs **A** and **B** of the same skill on the same input; one is the current prompt, one the new prompt, in random order. Please score each output 1–5 (F = fluency, A = accuracy/appropriateness, N = naturalness), as in `WP3_samples_groq_scores.md`, and pick a preference. Don't open `WP7a_persian_review_key.md` or `WP7a_ab_raw.jsonl` before scoring.

| Sample | Out | F | A | N | Prefer (A / B / =) | Note |
|---|---|---|---|---|---|---|
| s4 | A |  |  |  |  |  |
| s4 | B |  |  |  |  |  |
| s2 | A |  |  |  |  |  |
| s2 | B |  |  |  |  |  |
| t1 | A |  |  |  |  |  |
| t1 | B |  |  |  |  |  |
| c2 | A |  |  |  |  |  |
| c2 | B |  |  |  |  |  |
| c5 | A |  |  |  |  |  |
| c5 | B |  |  |  |  |  |
| n1 | A |  |  |  |  |  |
| n1 | B |  |  |  |  |  |
| n2 | A |  |  |  |  |  |
| n2 | B |  |  |  |  |  |
| n3 | A |  |  |  |  |  |
| n3 | B |  |  |  |  |  |

## s4 — EN text, trailing FA instruction → FA summary (A3)
Skill `summarizer` · instruction: Summarize the text in Persian

**Input**

````text
The city council of Riverton approved a 48 million dollar budget for public transport on Tuesday, after a debate that lasted more than six hours. The plan adds three new bus lines, extends the tram network by 7 kilometres and lowers monthly passes from 60 to 45 dollars for students and retirees. Supporters argued that cheaper fares will cut car traffic in the city centre by up to 15 percent within two years. Opponents, led by councillor Maria Lopez, warned that the plan relies on a state grant of 12 million dollars that has not yet been confirmed, and that delays could force the city to raise parking fees instead. Construction of the tram extension is scheduled to begin in March 2027, and the first new bus line should open in September. The council will review the project's costs every six months.

این متن را به فارسی خلاصه کن
````

**A**

````text
شورای شهر ریورتن پس از بحث‌های بیش از شش‌ساعته، بودجهٔ ۴۸ میلیون دلاری حمل‌ونقل عمومی را تصویب کرد؛ طرحی که شامل ایجاد سه خط اتوبوس جدید، گسترش ۷ کیلومتری شبکهٔ ترام و کاهش بلیت ماهانهٔ دانش‌آموزان و بازنشستگان از ۶۰ به ۴۵ دلار است. موافقان استدلال کردند که کاهش تعرفه‌ها تا دو سال دیگر ترافیک خودرو در مرکز شهر را تا ۱۵ درصد کاهش می‌دهد، اما مخالفان به رهبری شهردار ماریا لوپز هشدار دادند که این طرح به یارانهٔ ۱۲ میلیون دلاری ایالتی وابسته است که هنوز تأیید نشده و در صورت تأخیر، شهر ممکن است مجبور به افزایش هزینه‌های پارکینگ شود. ساخت بخش جدید ترام قرار است از مارس ۲۰۲۷ آغاز شود و اولین خط اتوبوس جدید در سپتامبر افتتاح می‌شود، در حالی که شورا هزینه‌های پروژه را هر شش ماه یک‌بار بازبینی خواهد کرد.
````

**B**

````text
شورای شهر ریورتن پس از بحث‌های بیش از شش‌ساعته، بودجه ۴۸ میلیون دلاری حمل‌ونقل عمومی را تصویب کرد که شامل ایجاد سه خط اتوبوس جدید، گسترش ۷ کیلومتری شبکه ترام و کاهش بلیط ماهانه دانشجویان و بازنشستگان از ۶۰ به ۴۵ دلار می‌شود. طرفداران این طرح مدعی‌اند که کاهش تعرفه‌ها تا دو سال آینده ترافیک خودرو در مرکز شهر را تا ۱۵ درصد کاهش خواهد داد، اما مخالفان به رهبری ماریا لوپز هشدار داده‌اند که این برنامه به یارانه ۱۲ میلیون دلاری ایالتی وابسته است که هنوز تأیید نشده و در صورت تأخیر، شهر مجبور به افزایش هزینه‌های پارکینگ خواهد شد. ساخت گسترش ترام قرار است در مارس ۲۰۲۷ آغاز شود و نخستین خط اتوبوس جدید در سپتامبر افتتاح می‌شود، در حالی که شورای شهر هر شش ماه یک‌بار هزینه‌های پروژه را بازبینی خواهد کرد.
````

## s2 — FA article → FA
Skill `summarizer` · instruction: Summarize the news text

**Input**

````text
این خبر را خلاصه کن:
سازمان هواشناسی اعلام کرد که از فردا یک سامانهٔ بارشی از غرب وارد کشور می‌شود و تا پایان هفته بیشتر استان‌ها را فرا می‌گیرد. بر اساس این گزارش، در استان‌های گیلان و مازندران احتمال بارش شدید و آب‌گرفتگی معابر وجود دارد و دمای هوا در تهران تا ۸ درجه کاهش می‌یابد. این سازمان از کشاورزان خواسته است برای حفاظت از محصولات گلخانه‌ای اقدام کنند و به رانندگان توصیه کرده است از سفرهای غیرضروری به مناطق کوهستانی خودداری کنند. کارشناسان می‌گویند این بارش‌ها می‌تواند بخشی از کمبود آب سدهای استان تهران را جبران کند، اما برای رفع کامل خشک‌سالی کافی نیست. به گفتهٔ مدیرکل پیش‌بینی، از روز جمعه هوا به‌تدریج پایدار می‌شود و دما دوباره افزایش می‌یابد.
````

**A**

````text
سازمان هواشناسی اعلام کرد که از فردا یک سامانهٔ بارشی وارد کشور می‌شود که در گیلان و مازندران احتمال آب‌گرفتگی معابر و در تهران کاهش ۸ درجه‌ای دما را در پی دارد؛ این سازمان از کشاورزان خواسته برای حفاظت از محصولات گلخانه‌ای اقدام کنند و به رانندگان توصیه کرده از سفرهای غیرضروری به مناطق کوهستانی خودداری کنند. کارشناسان می‌گویند این بارش‌ها می‌تواند بخشی از کمبود آب سدهای استان تهران را جبران کند، اما برای رفع کامل خشک‌سالی کافی نیست و به گفتهٔ مدیرکل پیش‌بینی، از روز جمعه هوا به‌تدریج پایدار می‌شود و دما دوباره افزایش می‌یابد.
````

**B**

````text
سازمان هواشناسی پیش‌بینی کرد که از فردا یک سامانهٔ بارشی وارد کشور شده و تا پایان هفته بیشتر استان‌ها را فرا می‌گیرد؛ در این میان، احتمال بارش شدید و آب‌گرفتگی در گیلان و مازندران و کاهش ۸ درجه‌ای دما در تهران وجود دارد. این بارش‌ها می‌تواند بخشی از کمبود آب سدهای تهران را جبران کند، اما برای رفع کامل خشک‌سالی کافی نیست و هوا از روز جمعه به‌تدریج پایدار می‌شود.
````

## t1 — EN→FA, numbers, names, time
Skill `translator` · instruction: Translate the provided text into Persian

**Input**

````text
Translate into Persian: The quarterly report shows a 12% increase in sales, mainly in Tehran and Isfahan. We'll discuss it on Monday at 10:30.
````

**A**

````text
گزارش فصلی نشان‌دهندهٔ ۱۲ درصد افزایش فروش است، عمدتاً در تهران و اصفهان. این موضوع را روز دوشنبه ساعت ۱۰:۳۰ بررسی می‌کنیم.
````

**B**

````text
گزارش فصلی نشان‌دهندهٔ ۱۲ درصد افزایش در فروش است که عمدتاً در تهران و اصفهان رخ داده است. این موضوع را روز دوشنبه ساعت ۱۰:۳۰ بحث خواهیم کرد.
````

## c2 — emotional disclosure (FA)
Skill `general_chat` · instruction: Respond to the user's feelings

**Input**

````text
حالم خوب نیست، امروز خیلی خسته و بی‌حوصله‌ام.
````

**A**

````text
متأسفم که این‌طور احساس می‌کنی. کاملاً درک می‌کنم؛ گاهی اوقات روزها سنگین می‌شوند و انرژی‌مان تخلیه می‌شود. لطفاً به خودت سخت نگیر.

اگر دوست داری کمی حرف بزنیم که چه چیزی باعث این خستگی شده، من اینجام. یا اگر ترجیح می‌دهی فقط استراحت کنی، حق داری. الان چه چیزی می‌تواند کمی حالت را بهتر کند؟
````

**B**

````text
حق داری خسته باشی، روزها گاهی سنگین می‌گذرن. یه چای یا آب بخور و پاشو یه کم دراز بکش. دوست داری یه کم حرف بزنیم یا فقط می‌خوای یه چیزی بخونی که حوصله‌ات پُر بشه؟
````

## c5 — degraded fallback (router failed)
Skill `general_chat` · instruction: Respond to the user's message

**Input**

````text
یه چیزی بگو که روزم بهتر بشه
````

**A**

````text
حق داری گاهی روزها سنگین و بی‌معنی به نظر برسن. یه پیشنهاد کوچیک: همین الان یه لیوان چای یا قهوه داغ درست کن و با دقت بخور. فقط همین یه کار ساده می‌تونه یه لحظه‌ی آروم بهت بده. اگه دوست داشتی بگو چی اذیتت می‌کنه، شاید با هم یه راه‌حل ساده پیدا کنیم.
````

**B**

````text
فکر کن به لحظه‌ای که امروز، حتی اگر کوچک بوده، احساس خوبی داشتی یا چیزی را درست انجام داده‌ای. تو لایق آرامش و شادی هستی. یه نفس عمیق بکش و با خودت مهربون‌تر باش. امیدوارم بقیه‌ی روزت پر از لحظات نورانی و دلگرم‌کننده باشه. ❤️
````

## n1 — new: EN news → FA summary (target 1, 2)
Skill `summarizer` · instruction: Summarize the news in Persian

**Input**

````text
The national rail operator announced on Thursday that ticket prices on intercity routes will rise by 9 percent from 1 February, the second increase in a year. The company said the extra revenue will pay for 40 new carriages and faster Wi-Fi on its busiest lines. Passenger groups, led by commuter advocate Hannah Weiss, criticised the decision and said that many people who travel to work every day can no longer afford the train. The transport ministry asked the operator to keep its discounts for students and pensioners, and advised regular travellers to buy annual passes before the end of January, while the old prices still apply. Officials still expect passenger numbers to grow by 5 percent this year. A parliamentary committee will question the company's chief executive next week.

این خبر را به فارسی خلاصه کن
````

**A**

````text
شرکت ملی راه‌آهن اعلام کرد که قیمت بلیت‌های مسیرهای بین‌شهری از ۱ فوریه به میزان ۹ درصد افزایش می‌یابد؛ این دومین افزایش قیمت در طول یک سال است. این شرکت گفت که درآمد حاصل از این افزایش صرف خرید ۴۰ واگن جدید و بهبود سرعت وای‌فای در شلوغ‌ترین خطوط خواهد شد. گروه‌های مسافری، به رهبری هانا وایس، از این تصمیم انتقاد کردند و گفتند بسیاری از افراد که هر روز برای کار سفر می‌کنند، دیگر توان پرداخت هزینه قطار را ندارند. وزارت حمل‌ونقل از اپراتور خواست تخفیف‌های دانشجویان و بازنشستگان را حفظ کند و به مسافران منظم توصیه کرد پیش از پایان ژانویه، زمانی که هنوز قیمت‌های قبلی اعمال می‌شود، بلیت سالانه بخرند. مقامات همچنان انتظار دارند تعداد مسافران امسال ۵ درصد رشد کند و یک کمیته پارلمانی هفته آینده از مدیرعامل شرکت سوال خواهد کرد.
````

**B**

````text
قیمت بلیت‌های مسیرهای بین‌شهری ریل ملی از ۱ فوریه با ۹ درصد افزایش مواجه می‌شود که دومین افزایش در یک سال است و درآمد حاصله برای خرید ۴۰ واگن جدید و ارتقای وای‌فای در شلوغ‌ترین خطوط هزینه خواهد شد. گروه‌های مسافری به رهبری هانا وایس از این تصمیم انتقاد کرده و اعلام کردند بسیاری از مسافران روزانه دیگر توان پرداخت هزینه قطار را ندارند. وزارت حمل‌ونقل از اپراتور خواسته تخفیف‌های دانشجویان و بازنشستگان حفظ شود و به مسافران منظم توصیه کرده پیش از پایان ژانویه با قیمت‌های قبلی بلیت سالانه خریداری کنند، در حالی که مسئولان همچنان انتظار ۵ درصد رشد تعداد مسافران در امسال را دارند و کمیته پارلمانی هفته آینده با مدیرعامل شرکت گفت‌وگو خواهد کرد.
````

## n2 — new: technical EN → FA (target 3)
Skill `translator` · instruction: Translate the text into Persian

**Input**

````text
Translate into Persian: Our open-source machine learning library now supports distributed training on multiple GPUs, and the new release cuts memory usage by 30 percent. Users can download the pretrained models from the cloud and fine-tune them on their own datasets.
````

**A**

````text
کتابخانه یادگیری ماشین متن‌باز ما اکنون از آموزش توزیع‌شده روی چندین واحد پردازش گرافیکی (GPU) پشتیبانی می‌کند و نسخه جدید، مصرف حافظه را ۳۰ درصد کاهش می‌دهد. کاربران می‌توانند مدل‌های از پیش آموزش‌دیده را از ابر دانلود کرده و آن‌ها را بر روی مجموعه داده‌های خود تنظیم دقیق کنند.
````

**B**

````text
کتابخانهٔ یادگیری ماشین متن‌باز ما اکنون از آموزش توزیع‌شده روی چندین کارت گرافیک پشتیبانی می‌کند و نسخهٔ جدید، مصرف حافظه را ۳۰ درصد کاهش می‌دهد. کاربران می‌توانند مدل‌های از پیش آموزش‌دیده را از فضای ابری دانلود کرده و آن‌ها را روی مجموعه‌های دادهٔ خود بهینه‌سازی کنند.
````

## n3 — new: colloquial FA chat line (target 4)
Skill `general_chat` · instruction: Respond to the user's feelings

**Input**

````text
امروز تو جلسه حسابی ضایع شدم، رئیسم جلوی همه ازم ایراد گرفت. حوصله هیچی رو ندارم
````

**A**

````text
حق داری ناراحت باشی؛ اون لحظه واقعاً آزاردهنده‌ست.
پیشنهاد می‌کنم فعلاً از اجتماع فاصله بگیری، یه چای یا قهوه بزن و فقط نفس بکشی.
اگه دوست داشتی، بگو دقیقاً چه اتفاقی افتاد تا با هم یه کم حرف بزنیم.
````

**B**

````text
کاملاً درکت می‌کنم؛ این وضعیت واقعاً آزاردهنده و خسته‌کننده است. حق داری که الان حوصله‌ای نداشته باشی.

فکر می‌کنی الان بهترین کار اینه که یه کم با خودت تنها باشی و ذهنت رو خالی کنی؟ یا ترجیح میدی درباره‌ش حرف بزنی تا سبک‌تر بشی؟
````
