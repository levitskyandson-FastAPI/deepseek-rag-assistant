import os
import re
import json
import httpx
from dotenv import load_dotenv
from datetime import datetime, timedelta, timezone
import sys
from services.amocrm import AmoCRM
import services.amocrm as amocrm_module

print("AMOCRM PATH:", amocrm_module.__file__)

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

from services.leads import save_lead

from services.amocrm import AmoCRM
from services.supabase import supabase
from core.logger import logger

# ======================================================
# INIT
# ======================================================

load_dotenv()

API_URL = os.getenv("API_URL", "http://127.0.0.1:8000/chat/")


PHONE_REGEX = re.compile(r"(\+?\d[\d\s\-\(\)]{9,}\d)")
MSK = timezone(timedelta(hours=3))

# ======================================================
# LEAD ENGINE
# ======================================================

LEAD_TEMPLATE = {
    "name": None,
    "company": None,
    "industry": None,
    "problem": None,  # боль/задача клиента
    "current_process": None,  # как сейчас
    "volume": None,  # объём
    "goal": None,  # цель/ожидаемый результат
    "budget": None,  # бюджет
    "position": None,  # ЛПР
    "phone": None,  # телефон
    "preferred_date": None,  # когда удобно созвониться
}

# Обязательные поля для отправки лида (SaaS, универсально)
REQUIRED_FIELDS = [
    "name",
    "company",
    "industry",
    "problem",
    "current_process",
    "volume",
    "goal",
    "budget",
    "phone",
    "preferred_date",
    "position",
]

JSON_RE = re.compile(r"<LEAD_JSON>\s*(\{.*?\})\s*</LEAD_JSON>", re.S)


def extract_patch(text: str) -> dict:
    m = JSON_RE.search(text or "")
    if not m:
        return {}
    try:
        obj = json.loads(m.group(1))
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def apply_patch(collected: dict, patch: dict):
    """Только непустые значения."""
    if not isinstance(patch, dict):
        return
    for k, v in patch.items():
        if k not in collected:
            continue
        if v is None:
            continue
        if isinstance(v, str) and not v.strip():
            continue
        collected[k] = v


def normalize_phone(raw: str) -> str | None:
    if not raw:
        return None
    p = re.sub(r"[^\d+]", "", raw)
    # простая валидация: >=10 цифр
    digits = re.sub(r"\D", "", p)
    if len(digits) < 10:
        return None
    return p


def extract_phone_and_date(text: str, old_preferred: str | None = None):
    if not text:
        return None, None

    base_date = datetime.now(MSK).date()

    phone = None
    preferred_date = None

    pm = PHONE_REGEX.search(text)
    if pm:
        phone = normalize_phone(pm.group(1))

    tl = text.lower()

    # --- определяем новую дату ---
    if "послезавтра" in tl:
        new_date = base_date + timedelta(days=2)
    elif "завтра" in tl:
        new_date = base_date + timedelta(days=1)
    elif "сегодня" in tl:
        new_date = base_date
    else:
        new_date = None

    # --- определяем время ---
    tm = re.search(r"(\d{1,2})[:.-](\d{2})", text)
    new_time = None
    if tm:
        hh = tm.group(1).zfill(2)
        mm = tm.group(2)
        new_time = f"{hh}:{mm}"

    # --- логика пересборки ---
    if new_date:
        date_str = new_date.strftime("%d.%m.%Y")
        preferred_date = f"{date_str} {new_time}" if new_time else date_str

    elif new_time and old_preferred:
        # меняем только время, дату оставляем
        old_date = old_preferred.split(" ")[0]
        preferred_date = f"{old_date} {new_time}"

    return phone, preferred_date


def missing_required(collected: dict) -> list[str]:
    return [f for f in REQUIRED_FIELDS if not collected.get(f)]


def is_ready_for_handoff(collected: dict) -> bool:
    return len(missing_required(collected)) == 0


def build_lead_summary(collected: dict) -> str:
    return f"""
Имя: {collected.get('name')}
Компания: {collected.get('company')}
Сфера: {collected.get('industry')}
Боль: {collected.get('problem')}
Как сейчас: {collected.get('current_process')}
Объём: {collected.get('volume')}
Цель: {collected.get('goal')}
Бюджет: {collected.get('budget')}
Должность: {collected.get('position')}

Телефон: {collected.get('phone')}
Созвон: {collected.get('preferred_date')}
"""


async def load_client(client_id: str):
    res = supabase.table("clients").select("*").eq("id", client_id).execute()

    if not res.data:
        raise ValueError("Client not found")

    client = res.data[0]

    if not client.get("is_active"):
        raise ValueError("Client inactive")

    return client


# ======================================================
# SESSIONS
# ======================================================


async def load_session(user_id: int, client_id: str):
    res = (
        supabase.table("sessions")
        .select("*")
        .eq("user_id", user_id)
        .eq("client_id", client_id)
        .execute()
    )

    if res.data:
        d = res.data[0]
        return {
            "conversation": json.loads(d["conversation"]),
            "collected": json.loads(d["collected"]),
            "lead_saved": d.get("lead_saved", False),
            "contact_id": d.get("contact_id"),
            "lead_id": d.get("lead_id"),
        }

    return {
        "conversation": [],
        "collected": LEAD_TEMPLATE.copy(),
        "lead_saved": False,
        "contact_id": None,
        "lead_id": None,
    }


async def save_session(user_id: int, client_id: str, session: dict):
    try:
        supabase.table("sessions").upsert(
            {
                "user_id": user_id,
                "client_id": client_id,
                "conversation": json.dumps(session["conversation"], ensure_ascii=False),
                "collected": json.dumps(session["collected"], ensure_ascii=False),
                "lead_saved": session["lead_saved"],
                "contact_id": session.get("contact_id"),
                "lead_id": session.get("lead_id"),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            on_conflict="user_id,client_id",
        ).execute()
    except Exception as e:
        logger.error(f"Ошибка сохранения сессии в Supabase: {e}", exc_info=True)
        # Не пробрасываем исключение дальше, чтобы бот не падал


# ======================================================
# CONVERSATION ENGINE (LLM)
# ======================================================


def build_system_prompt(history: str, collected: dict) -> str:
    today_str = datetime.now(MSK).strftime("%d.%m.%Y")
    miss = missing_required(collected)
    miss_str = ", ".join(miss) if miss else "нет"

    return f"""
Сегодняшняя дата: {today_str}

Если пользователь говорит:
- "сегодня" — это {today_str}
- "завтра" — это дата +1 день
- "послезавтра" — это дата +2 дня

Всегда преобразуй относительные даты в формат:
ДД.ММ.ГГГГ ЧЧ:ММ

Ты — SaaS AI-ассистент, работаешь для разных компаний.


Цель: естественный диалог + квалификация лида.
ВАЖНО: лид отправляется менеджеру ТОЛЬКО когда собраны поля:
{REQUIRED_FIELDS}

СЕЙЧАС НЕ ХВАТАЕТ: {miss_str}

    Правила:
    - Пиши как живой менеджер.
    - Максимум 1 вопрос за сообщение.
    - Не делай анкету из 10 пунктов.
    - Сначала короткая реакция, потом 1 вопрос.
    - Не обещай "отправил договор/письмо" — этого нет в коде.
    - Если пользователь ответил сразу несколькими фактами — вытащи их и НЕ переспрашивай.
    - В начале каждого сообщения употребляй разные слова одобрения а не только Отлично
    - Если не указана должность — спроси:
    - Подскажите, пожалуйста, какую должность вы занимаете в компании?
    
    СТИЛЬ И РАЗНООБРАЗИЕ:
    СТРОГИЕ ПРАВИЛА ПО РАЗНООБРАЗИЮ:

    1. Запрещено начинать ответы одним и тем же словом два раза подряд.

    2. Слово "Отлично" можно использовать НЕ ЧАЩЕ одного раза за диалог.

    3. Если в предыдущем ответе использовалось:
   - Отлично
   - Понял
   - Благодарю
   - Хорошо
   - Спасибо

   то в следующем ответе ОБЯЗАТЕЛЬНО используй другое слово.

    4. Чередуй одобрительные формулировки из списка:
   - Понимаю
   - Благодарю за уточнение
   - Хороший момент
   - Это логично
   - Согласен
   - Вижу задачу
   - Спасибо, это важно
   - Понял вас
   - Да, это актуально
   - Хорошо
   - Принял
     
    Перед формированием ответа проверь:
    - не повторяется ли начальное слово из предыдущего сообщения
    - не используется ли "Отлично" чаще одного раза
    Если повторяется — обязательно замени.

    5. Нельзя использовать слово "Отлично" чаще одного раза за всю беседу.

   6. НЕ повторяй часто формулировку "Чтобы мы могли".
   Используй альтернативы:
   - Чтобы предложить точное решение
   - Чтобы рассчитать подходящий формат
   - Чтобы оценить масштаб
   - Чтобы подобрать оптимальную конфигурацию
   - Чтобы понимать картину полностью
   - Чтобы предложить лучший сценарий внедрения
   - Чтобы сформировать корректное предложение
   - Чтобы выстроить решение под вас
   - Чтобы определить формат интеграции

   7. Формулируй естественно. 
   Запрещён шаблонный стиль.
   Каждый ответ должен звучать как живой менеджер, а не как скрипт.

   Если одно и то же слово уже использовалось в предыдущем ответе —
   запрещено начинать им новый ответ.

   Критично:
   - В КАЖДОМ ответе ты ОБЯЗАН вернуть блок <LEAD_JSON>...</LEAD_JSON>.
   - Заполняй ТОЛЬКО то, что реально понял из сообщения пользователя.
   - Если поле не найдено — не добавляй его в JSON.

   Формат ответа:
   1) Текст пользователю
   2) Затем на новой строке JSON блок:

   Не используй имя пользователя,
   пока он сам его не написал в текущем диалоге.

<LEAD_JSON>
{{"field":"value"}}
</LEAD_JSON>

Поля которые можно заполнять:
- name
- company
- industry
- problem
- current_process
- volume
- goal
- budget
- position

- phone
- preferred_date (обязательно в формате ДД.ММ.ГГГГ ЧЧ:ММ)

История:
{history}

Собранные данные:
{json.dumps(collected, ensure_ascii=False)}
"""


def build_after_handoff_prompt(history: str, collected: dict) -> str:
    return f"""
Ты — AI-ассистент компании.

Клиент уже оставил заявку.
Лид передан менеджеру.

РЕЖИМ: SUPPORT + RAG

Разрешено:
- Отвечать на вопросы клиента
- Использовать информацию из документов
- Работать с возражениями
- Аргументировать преимуществами
- Изменять телефон
- Изменять дату/время созвона

Запрещено:
- Продолжать квалификацию
- Собирать бюджет, боль, объём
- Назначать новую консультацию без запроса клиента

Если клиент просит изменить:
- телефон → обнови phone
- время → обнови preferred_date

Если информации нет в документах —
честно скажи, что уточнишь у менеджера.

Отвечай кратко.
Как живой менеджер.
Без шаблонности.

Текущие данные:
{json.dumps(collected, ensure_ascii=False)}

История:
{history}
"""


# ======================================================
# CRM ADAPTER
# ======================================================


async def notify_manager(context, lead: dict, manager_chat_id: str | None):
    if not manager_chat_id:
        logger.warning("MANAGER_CHAT_ID is None — notify skipped")
        return

    msg = "🔥 Новый лид\n\n" + build_lead_summary(lead)

    await context.bot.send_message(
        chat_id=manager_chat_id,
        text=msg,
    )


# ======================================================
# MAIN HANDLER
# ======================================================


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    CLIENT_ID = context.application.bot_data.get("client_id")

    # Проверка наличия client_id
    if not CLIENT_ID:
        logger.error("client_id отсутствует в bot_data")
        await update.message.reply_text("Ошибка конфигурации бота.")
        return

    # Загрузка клиента с обработкой ошибок
    try:
        CLIENT_DATA = await load_client(CLIENT_ID)
    except Exception as e:
        logger.error(f"Ошибка загрузки клиента {CLIENT_ID}: {e}")
        await update.message.reply_text("Технический сбой, попробуйте позже.")
        return

    # Загрузка настроек клиента
    crm_settings = CLIENT_DATA.get("crm_settings") or {}
    if isinstance(crm_settings, str):
        try:
            crm_settings = json.loads(crm_settings)
        except:
            crm_settings = {}
    MANAGER_CHAT_ID = crm_settings.get("telegram_manager_chat_id") or CLIENT_DATA.get(
        "manager_chat_id"
    )
    AMO_ACCOUNT_KEY = CLIENT_DATA.get("amo_account_key")

    crm = None
    if AMO_ACCOUNT_KEY:
        try:
            crm = AmoCRM(AMO_ACCOUNT_KEY)
        except Exception as e:
            logger.exception(e)

    text = update.message.text or ""

    # Загрузка сессии с обработкой ошибок
    try:
        session = await load_session(user_id, CLIENT_ID)
    except Exception as e:
        logger.error(f"Ошибка загрузки сессии: {e}")
        await update.message.reply_text(
            "Не удалось загрузить диалог, попробуйте /start."
        )
        return

    session["conversation"].append({"role": "user", "content": text})

    # ======================================================
    # 1️⃣ ИЗВЛЕКАЕМ ТЕЛЕФОН И ДАТУ ИЗ СООБЩЕНИЯ (до LLM)
    # ======================================================
    old_phone = session["collected"].get("phone")
    old_date = session["collected"].get("preferred_date")

    phone_regex, preferred_date_regex = extract_phone_and_date(text, old_date)

    if phone_regex:
        session["collected"]["phone"] = phone_regex
    if preferred_date_regex:
        session["collected"]["preferred_date"] = preferred_date_regex

    # ======================================================
    # 2️⃣ ПОДГОТОВКА ПРОМПТА И ВЫЗОВ LLM
    # ======================================================
    history_str = "\n".join(
        f"{m['role']}: {m['content']}" for m in session["conversation"][-30:]
    )

    if session.get("lead_saved"):
        system_prompt = build_after_handoff_prompt(history_str, session["collected"])
    else:
        system_prompt = build_system_prompt(history_str, session["collected"])

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                API_URL,
                json={
                    "user_id": CLIENT_ID,
                    "message": text,
                    "system_extra": system_prompt,
                    "use_rag": True,
                    "context_info": json.dumps(
                        {"client_id": CLIENT_ID, "source": "telegram"},
                        ensure_ascii=False,
                    ),
                },
            )

        data = response.json()
        reply = (data.get("reply") or "").strip()

        # Применяем JSON-патч от LLM
        patch = extract_patch(reply)
        reply = JSON_RE.sub("", reply).strip()  # убираем JSON из ответа пользователю
        if patch:
            apply_patch(session["collected"], patch)

    except Exception as e:
        logger.error(f"LLM ERROR: {e}")
        reply = "Произошёл сбой. Повторите запрос."

    # ======================================================
    # 3️⃣ ОПРЕДЕЛЯЕМ ИЗМЕНЕНИЯ (сравниваем с исходными old_*)
    # ======================================================
    new_phone = session["collected"].get("phone")
    new_date = session["collected"].get("preferred_date")

    phone_changed = new_phone and new_phone != old_phone
    date_changed = new_date and new_date != old_date

    # ======================================================
    # 4️⃣ ОБНОВЛЕНИЕ CRM (если лид уже создан)
    # ======================================================
    if session.get("lead_saved") and crm:
        try:
            if phone_changed and session.get("contact_id"):
                crm.update_contact_phone(session["contact_id"], new_phone)
                logger.info("✅ Phone updated in AmoCRM")
                # Подтверждение пользователю
                await update.message.reply_text(
                    f"✅ Телефон изменён на **{new_phone}**."
                )

            if date_changed and session.get("lead_id"):
                crm.update_lead_field(session["lead_id"], "meeting_time", new_date)
                logger.info("✅ Meeting time updated in AmoCRM")
                # Подтверждение пользователю
                await update.message.reply_text(
                    f"✅ Дата созвона изменена на **{new_date}**."
                )
        except Exception as e:
            logger.error("AmoCRM update error")
            logger.exception(e)

        # Уведомляем менеджера об изменениях (только если что-то изменилось)
        if phone_changed or date_changed:
            await notify_manager(context, session["collected"], MANAGER_CHAT_ID)

    print("COLLECTED:", session["collected"])
    print("MISSING:", missing_required(session["collected"]))

    # ======================================================
    # 5️⃣ ПЕРЕДАЧА ЛИДА МЕНЕДЖЕРУ (если все поля собраны)
    # ======================================================
    if (not session["lead_saved"]) and is_ready_for_handoff(session["collected"]):
        # Сохраняем в базу данных
        try:
            await save_lead(
                telegram_user_id=user_id,
                phone=session["collected"].get("phone"),
                name=session["collected"].get("name"),
                company=session["collected"].get("company"),
                industry=session["collected"].get("industry"),
                pain=session["collected"].get("problem"),
                goal=session["collected"].get("goal"),
                preferred_date=session["collected"].get("preferred_date"),
                extra_data={**session["collected"], "source": "telegram"},
            )
        except Exception as e:
            logger.error(f"save_lead error: {e}")

        # Создаём лид в AmoCRM
        if crm:
            try:
                amo_ids = crm.create_lead(
                    {
                        "name": session["collected"].get("name"),
                        "phone": session["collected"].get("phone"),
                        "problem": session["collected"].get("problem"),
                        "goal": session["collected"].get("goal"),
                        "volume": session["collected"].get("volume"),
                        "meeting_time": session["collected"].get("preferred_date"),
                        "sphere": session["collected"].get("industry"),
                        "budget": session["collected"].get("budget"),
                        "position": session["collected"].get("position"),
                        "company": session["collected"].get("company"),
                    }
                )
                session["contact_id"] = amo_ids["contact_id"]
                session["lead_id"] = amo_ids["lead_id"]
            except Exception as e:
                logger.error("AMO CRM ERROR:", exc_info=True)

        # Уведомляем менеджера (ОДИН РАЗ)
        await notify_manager(context, session["collected"], MANAGER_CHAT_ID)

        # Помечаем лид как сохранённый
        session["lead_saved"] = True

        # Сохраняем сессию
        try:
            await save_session(user_id, CLIENT_ID, session)
        except Exception as e:
            logger.error(f"Не удалось сохранить сессию при передаче лида: {e}")

        # Отправляем пользователю сводку
        reply_text = build_lead_summary(session["collected"])
        await update.message.reply_text(reply_text)
        return

    # ======================================================
    # 6️⃣ ОБЫЧНЫЙ ОТВЕТ (лид ещё не готов)
    # ======================================================
    session["conversation"].append({"role": "assistant", "content": reply})
    await save_session(user_id, CLIENT_ID, session)
    await update.message.reply_text(reply or "Можете уточнить?")


# ======================================================
# START
# ======================================================


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("START HANDLER TRIGGERED")

    user_id = update.effective_user.id

    CLIENT_ID = context.application.bot_data.get("client_id")
    if not CLIENT_ID:
        raise ValueError("client_id not found in bot_data")

    # 🔥 Динамически загружаем клиента
    CLIENT_DATA = await load_client(CLIENT_ID)

    session = {
        "conversation": [],
        "collected": LEAD_TEMPLATE.copy(),
        "lead_saved": False,
        "contact_id": None,
        "lead_id": None,
    }

    await save_session(user_id, CLIENT_ID, session)

    company_name = CLIENT_DATA.get("name") or "компания"
    bot_name = CLIENT_DATA.get("bot_name") or "AI-ассистент"

    welcome_message = f"""
Здравствуйте.

{company_name} | {bot_name}

Опишите ваш запрос.
"""

    await update.message.reply_text(welcome_message.strip())
