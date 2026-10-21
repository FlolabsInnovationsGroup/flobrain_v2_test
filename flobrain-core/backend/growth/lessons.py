"""Academy lessons: short, shipped lessons about using FloBrain well (flag ``academy``).

Each lesson has an English and an Arabic body (markdown), a "try it" link into the product (a path
under ``/w/<org>``), and a short check. ``answer`` is the index of the right option and never leaves
the server before the person answers. Titles and summaries are translated in the frontend phrase
file ``messages/phrases/<lang>/academy.json``; bodies and checks carry their Arabic here.

``feature`` names the flag the lesson is about (or None). The coach uses it with ``signal`` (a
cheap count of the person's own activity, see ``growth.academy.own_activity``) to say what they
have not tried yet.
"""

LESSONS = [
    {
        "key": "good-asks",
        "title": "Write good asks",
        "summary": "Get useful answers on the first try: say the goal, the context and the format.",
        "minutes": 4,
        "feature": None,
        "signal": "ai_answers",
        "try_it": {"label": "Ask something", "path": "/ask"},
        "body": (
            "## Say what you want, not just the topic\n\n"
            "A good ask has three parts:\n\n"
            "1. **The goal.** \"Draft a reply to the client that accepts the new date\" beats \"client email\".\n"
            "2. **The context.** Name the room, document or meeting. FloBrain only reads what you can read, "
            "so pointing at the right source matters.\n"
            "3. **The format.** \"Five bullet points\", \"a table\", \"under 100 words\", \"in Arabic\".\n\n"
            "## Check the sources\n\n"
            "Answers that use your workspace show their sources. Open one before you forward an answer. "
            "If there are no sources, the answer is general knowledge, not your company's facts.\n\n"
            "## Iterate\n\n"
            "Reply with what to change: \"shorter\", \"more formal\", \"add the budget line\". "
            "You don't need to start over."
        ),
        "body_ar": (
            "## قل ما تريده، لا الموضوع فقط\n\n"
            "الطلب الجيد له ثلاثة أجزاء:\n\n"
            "1. **الهدف.** \"اكتب ردًا على العميل يقبل الموعد الجديد\" أفضل من \"بريد العميل\".\n"
            "2. **السياق.** اذكر الغرفة أو المستند أو الاجتماع. لا يقرأ FloBrain إلا ما يمكنك قراءته، "
            "لذلك يهم أن تشير إلى المصدر الصحيح.\n"
            "3. **الشكل.** \"خمس نقاط\"، \"جدول\"، \"أقل من 100 كلمة\"، \"بالعربية\".\n\n"
            "## راجع المصادر\n\n"
            "الإجابات التي تستخدم مساحة عملك تعرض مصادرها. افتح أحدها قبل أن تعيد إرسال الإجابة. "
            "إذا لم توجد مصادر فالإجابة معرفة عامة، وليست حقائق شركتك.\n\n"
            "## حسّن الإجابة\n\n"
            "رد بما تريد تغييره: \"أقصر\"، \"أكثر رسمية\"، \"أضف بند الميزانية\". لا داعي للبدء من جديد."
        ),
        "check": [
            {
                "question": "Which ask is most likely to get a useful answer?",
                "question_ar": "أي طلب أقرب إلى إجابة مفيدة؟",
                "options": [
                    "Client email",
                    "Draft a short reply to Acme accepting the new delivery date, in a friendly tone",
                    "Help",
                ],
                "options_ar": ["بريد العميل", "اكتب ردًا قصيرًا على Acme يقبل موعد التسليم الجديد بنبرة ودية", "ساعدني"],
                "answer": 1,
            },
            {
                "question": "An answer shows no sources. What does that mean?",
                "question_ar": "إجابة لا تعرض أي مصادر. ماذا يعني ذلك؟",
                "options": [
                    "It came from your company's documents",
                    "It is general knowledge, not your workspace's facts",
                    "It was approved by an admin",
                ],
                "options_ar": ["جاءت من مستندات شركتك", "إنها معرفة عامة، وليست حقائق مساحة عملك", "وافق عليها مسؤول"],
                "answer": 1,
            },
            {
                "question": "The draft is too long. What should you do?",
                "question_ar": "المسودة طويلة جدًا. ماذا تفعل؟",
                "options": ["Start a new chat", "Reply \"shorter, under 80 words\"", "Delete the buddy"],
                "options_ar": ["ابدأ محادثة جديدة", "رد بعبارة \"أقصر، أقل من 80 كلمة\"", "احذف المساعد"],
                "answer": 1,
            },
        ],
    },
    {
        "key": "build-buddy",
        "title": "Build your own buddy",
        "summary": "Give a buddy one job, clear instructions, the right sources and only the actions it needs.",
        "minutes": 6,
        "feature": "buddies",
        "signal": "buddies_made",
        "try_it": {"label": "Open Buddies", "path": "/buddies"},
        "body": (
            "## One buddy, one job\n\n"
            "A buddy is an AI helper with its own instructions. The best buddies do one thing well: "
            "\"answer admissions questions\", \"draft weekly client reports\".\n\n"
            "## Write the instructions like a brief\n\n"
            "Say who it helps, what good output looks like, and what it must never do. "
            "For example: \"Never promise a discount. Ask for the order number first.\"\n\n"
            "## Pick sources on purpose\n\n"
            "A buddy only reads what the person chatting can read. You can narrow it further to a few rooms. "
            "Fewer, better sources give better answers.\n\n"
            "## Give it only the actions it needs\n\n"
            "Actions like creating tasks always wait for approval. Still, leave out actions the buddy does not need.\n\n"
            "## Share when it works\n\n"
            "New buddies are private. Sharing with a team or the whole org needs an approval."
        ),
        "body_ar": (
            "## مساعد واحد لمهمة واحدة\n\n"
            "المساعد (buddy) مساعد ذكي له تعليماته الخاصة. أفضل المساعدين يتقنون مهمة واحدة: "
            "\"الرد على أسئلة القبول\"، \"كتابة تقارير العملاء الأسبوعية\".\n\n"
            "## اكتب التعليمات كأنها موجز عمل\n\n"
            "قل من يساعد، وكيف يبدو الناتج الجيد، وما الذي يجب ألا يفعله أبدًا. "
            "مثلًا: \"لا تعد بخصم أبدًا. اطلب رقم الطلب أولًا.\"\n\n"
            "## اختر المصادر بعناية\n\n"
            "لا يقرأ المساعد إلا ما يستطيع الشخص المتحدث معه قراءته، ويمكنك حصره في غرف قليلة. "
            "مصادر أقل وأفضل تعني إجابات أفضل.\n\n"
            "## امنحه الإجراءات التي يحتاجها فقط\n\n"
            "الإجراءات مثل إنشاء المهام تنتظر الموافقة دائمًا. ومع ذلك لا تضف إجراءات لا يحتاجها.\n\n"
            "## شاركه عندما ينجح\n\n"
            "المساعدون الجدد خاصون. المشاركة مع فريق أو مع المؤسسة كلها تحتاج إلى موافقة."
        ),
        "check": [
            {
                "question": "What makes a buddy work best?",
                "question_ar": "ما الذي يجعل المساعد يعمل بأفضل شكل؟",
                "options": ["Every tool and every source", "One clear job and focused sources", "A very long name"],
                "options_ar": ["كل الأدوات وكل المصادر", "مهمة واحدة واضحة ومصادر محددة", "اسم طويل جدًا"],
                "answer": 1,
            },
            {
                "question": "Can a buddy read a room the person chatting with it can't read?",
                "question_ar": "هل يستطيع المساعد قراءة غرفة لا يستطيع الشخص المتحدث معه قراءتها؟",
                "options": ["Yes, if its creator could", "No, never", "Only on weekends"],
                "options_ar": ["نعم، إذا كان منشئه يستطيع", "لا، أبدًا", "في عطلة نهاية الأسبوع فقط"],
                "answer": 1,
            },
            {
                "question": "Who can use a buddy you just built?",
                "question_ar": "من يستطيع استخدام مساعد أنشأته للتو؟",
                "options": ["Only you, until a share is approved", "Everyone in the org", "Anyone on the internet"],
                "options_ar": ["أنت فقط، حتى تتم الموافقة على مشاركته", "كل من في المؤسسة", "أي شخص على الإنترنت"],
                "answer": 0,
            },
        ],
    },
    {
        "key": "approvals",
        "title": "Set approvals you can trust",
        "summary": "Buddies propose, people decide. Learn what waits for approval and how to review it fast.",
        "minutes": 4,
        "feature": "ai_actions",
        "signal": "approvals",
        "try_it": {"label": "Open Approvals", "path": "/approvals"},
        "body": (
            "## Buddies propose, people decide\n\n"
            "When a buddy wants to create a task, post in a room or write to another app, it makes a proposal. "
            "Nothing happens until a person approves it. Waiting items are amber everywhere in FloBrain.\n\n"
            "## Review the arguments, not just the title\n\n"
            "Open the proposal and read what will be sent: the room, the people, the text. "
            "You can edit before approving.\n\n"
            "## Proposals expire\n\n"
            "An old proposal stops being valid, so a stale action can't run later by accident.\n\n"
            "## Admins set the rules\n\n"
            "Admins choose which actions buddies may offer and who approves them. "
            "Writes to outside apps always need an approval unless an admin policy says otherwise."
        ),
        "body_ar": (
            "## المساعد يقترح والإنسان يقرر\n\n"
            "عندما يريد المساعد إنشاء مهمة أو النشر في غرفة أو الكتابة في تطبيق آخر، يقدم اقتراحًا. "
            "لا يحدث شيء حتى يوافق عليه شخص. العناصر المنتظرة تظهر باللون الكهرماني في كل مكان.\n\n"
            "## راجع التفاصيل لا العنوان فقط\n\n"
            "افتح الاقتراح واقرأ ما سيُرسل: الغرفة والأشخاص والنص. يمكنك التعديل قبل الموافقة.\n\n"
            "## الاقتراحات تنتهي صلاحيتها\n\n"
            "الاقتراح القديم يفقد صلاحيته، فلا يُنفذ إجراء قديم لاحقًا بالخطأ.\n\n"
            "## المسؤولون يضعون القواعد\n\n"
            "يختار المسؤولون الإجراءات التي يمكن للمساعدين اقتراحها ومن يوافق عليها. "
            "الكتابة في التطبيقات الخارجية تحتاج دائمًا إلى موافقة ما لم تنص سياسة المسؤول على غير ذلك."
        ),
        "check": [
            {
                "question": "A buddy proposes posting a message. When is it posted?",
                "question_ar": "اقترح مساعد نشر رسالة. متى تُنشر؟",
                "options": ["Right away", "After a person approves it", "Never"],
                "options_ar": ["فورًا", "بعد أن يوافق عليها شخص", "أبدًا"],
                "answer": 1,
            },
            {
                "question": "What should you check before approving?",
                "question_ar": "ماذا تراجع قبل الموافقة؟",
                "options": ["Only the title", "What will be sent and to whom", "The buddy's icon"],
                "options_ar": ["العنوان فقط", "ما سيُرسل وإلى من", "أيقونة المساعد"],
                "answer": 1,
            },
        ],
    },
    {
        "key": "automations",
        "title": "Automate the boring parts",
        "summary": "Describe a routine in plain words and FloBrain turns it into a workflow with approval steps.",
        "minutes": 5,
        "feature": "automations",
        "signal": "automations",
        "try_it": {"label": "Open Workflows", "path": "/automations"},
        "body": (
            "## Start from the routine you repeat\n\n"
            "\"Every Friday, collect what each client project finished and draft a report\" is a workflow. "
            "Describe it in plain words and the automation buddy proposes the steps.\n\n"
            "## Triggers, steps and approvals\n\n"
            "A workflow starts on a schedule or an event, runs its steps, and stops at an approval before "
            "anything leaves FloBrain or changes someone's data.\n\n"
            "## Start from a template\n\n"
            "Templates cover common jobs: invoice follow-ups, attendance reminders, weekly reports. "
            "They are created switched off, so you can read them first.\n\n"
            "## Watch the first runs\n\n"
            "Check the run history for a week before you trust a workflow fully."
        ),
        "body_ar": (
            "## ابدأ بالمهمة التي تكررها\n\n"
            "\"كل جمعة، اجمع ما أنهته مشاريع العملاء واكتب مسودة تقرير\" هذا سير عمل. "
            "صفه بكلمات بسيطة وسيقترح مساعد الأتمتة الخطوات.\n\n"
            "## المحفزات والخطوات والموافقات\n\n"
            "يبدأ سير العمل بجدول زمني أو بحدث، وينفذ خطواته، ويتوقف عند موافقة قبل أن يخرج أي شيء من "
            "FloBrain أو يغير بيانات أحد.\n\n"
            "## ابدأ من قالب\n\n"
            "القوالب تغطي المهام الشائعة: متابعة الفواتير، تذكيرات الحضور، التقارير الأسبوعية. "
            "تُنشأ القوالب متوقفة، لتقرأها أولًا.\n\n"
            "## راقب أول التشغيلات\n\n"
            "راجع سجل التشغيل لمدة أسبوع قبل أن تثق بسير العمل تمامًا."
        ),
        "check": [
            {
                "question": "What happens before a workflow sends something outside FloBrain?",
                "question_ar": "ماذا يحدث قبل أن يرسل سير العمل شيئًا خارج FloBrain؟",
                "options": ["Nothing, it just sends", "It stops for an approval", "It asks the AI to decide"],
                "options_ar": ["لا شيء، يرسل مباشرة", "يتوقف لانتظار موافقة", "يطلب من الذكاء الاصطناعي أن يقرر"],
                "answer": 1,
            },
            {
                "question": "How are workflows from templates created?",
                "question_ar": "كيف تُنشأ مسارات العمل من القوالب؟",
                "options": ["Switched off, so you can review them", "Already running", "Shared with every customer"],
                "options_ar": ["متوقفة لتراجعها", "تعمل مباشرة", "مشتركة مع كل العملاء"],
                "answer": 0,
            },
        ],
    },
    {
        "key": "data-buddy",
        "title": "Ask your data",
        "summary": "Connect a sheet or a database read-only, ask in plain words, and check the query behind every chart.",
        "minutes": 5,
        "feature": "data_buddy",
        "signal": "datasets",
        "try_it": {"label": "Open Data", "path": "/data"},
        "body": (
            "## Bring a dataset\n\n"
            "Upload a CSV, link a Google Sheet, or connect a database with a read-only user. "
            "FloBrain never writes to your data source.\n\n"
            "## Ask like you would ask an analyst\n\n"
            "\"Revenue by month this year, compared with last year\" works better than \"show sales\".\n\n"
            "## Always look at the query\n\n"
            "Every chart shows the query that made it. If a filter or a date range looks wrong, say so and ask again.\n\n"
            "## Schedule what you check every week\n\n"
            "Turn a good question into a scheduled report so it lands in a room every Monday."
        ),
        "body_ar": (
            "## أضف مجموعة بيانات\n\n"
            "ارفع ملف CSV أو اربط جدول Google أو اتصل بقاعدة بيانات بمستخدم للقراءة فقط. "
            "لا يكتب FloBrain أبدًا في مصدر بياناتك.\n\n"
            "## اسأل كما تسأل محللًا\n\n"
            "\"الإيرادات حسب الشهر هذا العام مقارنة بالعام الماضي\" أفضل من \"اعرض المبيعات\".\n\n"
            "## انظر دائمًا إلى الاستعلام\n\n"
            "كل رسم بياني يعرض الاستعلام الذي أنتجه. إذا بدا مرشح أو نطاق تاريخ خاطئًا، قل ذلك واسأل مجددًا.\n\n"
            "## جدول ما تراجعه كل أسبوع\n\n"
            "حوّل السؤال الجيد إلى تقرير مجدول يصل إلى غرفة كل يوم اثنين."
        ),
        "check": [
            {
                "question": "What access should a database connection have?",
                "question_ar": "ما الصلاحية التي يجب أن يملكها اتصال قاعدة البيانات؟",
                "options": ["Read-only", "Full admin", "Write access to every table"],
                "options_ar": ["قراءة فقط", "مسؤول كامل", "كتابة في كل الجداول"],
                "answer": 0,
            },
            {
                "question": "A chart looks wrong. What do you check first?",
                "question_ar": "يبدو رسم بياني خاطئًا. ماذا تراجع أولًا؟",
                "options": ["The colours", "The query shown under it", "Your password"],
                "options_ar": ["الألوان", "الاستعلام المعروض أسفله", "كلمة المرور"],
                "answer": 1,
            },
        ],
    },
    {
        "key": "meetings-to-tasks",
        "title": "Turn meetings into tasks",
        "summary": "Get a summary, decisions and action items after every meeting, then approve the tasks.",
        "minutes": 4,
        "feature": None,
        "signal": "meetings",
        "try_it": {"label": "Open Calendar", "path": "/calendar"},
        "body": (
            "## Record or transcribe\n\n"
            "Hold the meeting in FloBrain, or add the meeting bot to an outside call where your org allows it. "
            "Everyone sees that it is being recorded.\n\n"
            "## Read the summary\n\n"
            "After the meeting you get a summary, the decisions and the action items with owners.\n\n"
            "## Turn action items into tasks\n\n"
            "Ask the buddy \"make tasks from the action items\". It proposes the tasks; you approve them, "
            "and the owners get them in their task list.\n\n"
            "## Ask later\n\n"
            "\"What did we decide about the launch date?\" finds the answer in past meetings you attended."
        ),
        "body_ar": (
            "## سجّل أو فرّغ نصيًا\n\n"
            "عقد الاجتماع في FloBrain، أو أضف روبوت الاجتماعات إلى مكالمة خارجية حيث تسمح مؤسستك بذلك. "
            "يرى الجميع أن الاجتماع يُسجّل.\n\n"
            "## اقرأ الملخص\n\n"
            "بعد الاجتماع تحصل على ملخص والقرارات وبنود العمل مع المسؤولين عنها.\n\n"
            "## حوّل بنود العمل إلى مهام\n\n"
            "اطلب من المساعد \"أنشئ مهام من بنود العمل\". سيقترح المهام، وأنت توافق عليها، "
            "فتصل إلى قوائم مهام أصحابها.\n\n"
            "## اسأل لاحقًا\n\n"
            "\"ماذا قررنا بشأن موعد الإطلاق؟\" يجد الإجابة في الاجتماعات السابقة التي حضرتها."
        ),
        "check": [
            {
                "question": "How do action items become tasks?",
                "question_ar": "كيف تتحول بنود العمل إلى مهام؟",
                "options": ["Automatically, with no review", "The buddy proposes them and you approve", "You copy them by hand only"],
                "options_ar": ["تلقائيًا دون مراجعة", "يقترحها المساعد وأنت توافق", "تنسخها يدويًا فقط"],
                "answer": 1,
            },
            {
                "question": "Which meetings can you ask about later?",
                "question_ar": "عن أي اجتماعات يمكنك السؤال لاحقًا؟",
                "options": ["Every meeting in the company", "Meetings you can access", "None"],
                "options_ar": ["كل اجتماعات الشركة", "الاجتماعات التي يمكنك الوصول إليها", "لا شيء"],
                "answer": 1,
            },
        ],
    },
    {
        "key": "arabic-english",
        "title": "Work in Arabic and English",
        "summary": "Switch the interface language, ask in either language, and translate room messages.",
        "minutes": 3,
        "feature": "live_translation",
        "signal": None,
        "try_it": {"label": "Change language", "path": "/settings/profile"},
        "body": (
            "## Pick your interface language\n\n"
            "Choose Arabic, English, Turkish, French or Portuguese in your profile. Arabic switches the whole "
            "layout to right-to-left.\n\n"
            "## Ask in the language you think in\n\n"
            "Buddies answer in the language you write. Ask in Egyptian or Gulf Arabic, or in English, "
            "and say \"answer in English\" if you need to forward it.\n\n"
            "## Translate in rooms\n\n"
            "Where your admin has turned it on, each room message can be translated, so mixed teams read the same thread.\n\n"
            "## Keep names and numbers exact\n\n"
            "Check names, amounts and dates in any translation before you send it outside."
        ),
        "body_ar": (
            "## اختر لغة الواجهة\n\n"
            "اختر العربية أو الإنجليزية أو التركية أو الفرنسية أو البرتغالية من ملفك الشخصي. "
            "العربية تحوّل التخطيط كله من اليمين إلى اليسار.\n\n"
            "## اسأل باللغة التي تفكر بها\n\n"
            "يجيب المساعدون باللغة التي تكتب بها. اسأل بالعامية المصرية أو الخليجية أو بالإنجليزية، "
            "وقل \"أجب بالإنجليزية\" إذا كنت ستعيد إرسال الإجابة.\n\n"
            "## الترجمة في الغرف\n\n"
            "حيث فعّلها المسؤول، يمكن ترجمة كل رسالة في الغرفة، فيقرأ الفريق المختلط المحادثة نفسها.\n\n"
            "## حافظ على دقة الأسماء والأرقام\n\n"
            "راجع الأسماء والمبالغ والتواريخ في أي ترجمة قبل إرسالها إلى الخارج."
        ),
        "check": [
            {
                "question": "You ask a buddy in Arabic. What language does it answer in?",
                "question_ar": "سألت المساعد بالعربية. بأي لغة يجيب؟",
                "options": ["Always English", "Arabic, unless you ask otherwise", "A random language"],
                "options_ar": ["الإنجليزية دائمًا", "العربية، ما لم تطلب غير ذلك", "لغة عشوائية"],
                "answer": 1,
            },
            {
                "question": "What should you double-check in a translation before sending it outside?",
                "question_ar": "ماذا تراجع في الترجمة قبل إرسالها إلى الخارج؟",
                "options": ["Names, amounts and dates", "Font size", "Nothing"],
                "options_ar": ["الأسماء والمبالغ والتواريخ", "حجم الخط", "لا شيء"],
                "answer": 0,
            },
        ],
    },
    {
        "key": "security-basics",
        "title": "Security basics",
        "summary": "What FloBrain can see, what admins can't see, and how to keep secrets out of chats.",
        "minutes": 4,
        "feature": None,
        "signal": None,
        "try_it": {"label": "Open Privacy", "path": "/privacy"},
        "body": (
            "## AI never widens access\n\n"
            "Buddies, search and summaries use only what you can already open. Private rooms stay private, "
            "even from admins.\n\n"
            "## Don't paste secrets\n\n"
            "Never paste passwords, API keys or card numbers into a chat. Admins connect apps through settings, "
            "where keys are stored encrypted and shown only as the last four characters.\n\n"
            "## Check before you approve\n\n"
            "An approval is you saying \"yes, do this\". Read what will be sent.\n\n"
            "## Know your privacy page\n\n"
            "Your privacy page shows what is kept about you, lets you download it, and lets you keep your "
            "insights personal."
        ),
        "body_ar": (
            "## الذكاء الاصطناعي لا يوسّع صلاحياتك أبدًا\n\n"
            "المساعدون والبحث والملخصات تستخدم فقط ما يمكنك فتحه بالفعل. الغرف الخاصة تبقى خاصة، "
            "حتى عن المسؤولين.\n\n"
            "## لا تلصق الأسرار\n\n"
            "لا تلصق كلمات المرور أو مفاتيح API أو أرقام البطاقات في أي محادثة. يربط المسؤولون التطبيقات "
            "من الإعدادات، حيث تُخزن المفاتيح مشفرة ولا يظهر منها إلا آخر أربعة أحرف.\n\n"
            "## راجع قبل أن توافق\n\n"
            "الموافقة تعني أنك تقول \"نعم، نفّذ هذا\". اقرأ ما سيُرسل.\n\n"
            "## اعرف صفحة الخصوصية\n\n"
            "صفحة الخصوصية تعرض ما يُحفظ عنك، وتتيح لك تنزيله، وتتيح لك إبقاء رؤاك شخصية."
        ),
        "check": [
            {
                "question": "Can a buddy show you a document you can't open yourself?",
                "question_ar": "هل يستطيع المساعد أن يعرض لك مستندًا لا يمكنك فتحه بنفسك؟",
                "options": ["Yes", "No", "Only admins' buddies"],
                "options_ar": ["نعم", "لا", "مساعدو المسؤولين فقط"],
                "answer": 1,
            },
            {
                "question": "Where should an API key go?",
                "question_ar": "أين يجب وضع مفتاح API؟",
                "options": ["In a room message", "In the settings page made for it", "In a buddy's instructions"],
                "options_ar": ["في رسالة داخل غرفة", "في صفحة الإعدادات المخصصة له", "في تعليمات المساعد"],
                "answer": 1,
            },
            {
                "question": "Who can read a private room?",
                "question_ar": "من يستطيع قراءة غرفة خاصة؟",
                "options": ["Its members only", "Every admin", "Every buddy"],
                "options_ar": ["أعضاؤها فقط", "كل المسؤولين", "كل المساعدين"],
                "answer": 0,
            },
        ],
    },
]

BY_KEY = {lesson["key"]: lesson for lesson in LESSONS}
KEYS = [lesson["key"] for lesson in LESSONS]


def get(key):
    return BY_KEY.get(str(key or ""))


def passes(correct: int, total: int) -> bool:
    """Pass mark: at least two thirds right (2 of 3, 2 of 2)."""
    return total > 0 and correct * 3 >= total * 2
