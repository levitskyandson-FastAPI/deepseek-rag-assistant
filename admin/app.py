import os
import json
import asyncio
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, flash, abort
from dotenv import load_dotenv
import psycopg2
import psycopg2.extras
from psycopg2.extras import Json
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import tempfile
import aiofiles

# Принудительно задаём имя базы (для совместимости)
os.environ['DB_NAME'] = 'db1_prod'

# Добавляем путь к корню проекта
import sys
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from services.embeddings import process_document
from services.db import init_db_pool, get_db_pool
from core.logger import logger

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "supersecretkey")
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50 MB

# Подключение к PostgreSQL (синхронное, для работы Flask)
DB_PARAMS = {
    "host": os.getenv("DB_HOST"),
    "port": os.getenv("DB_PORT"),
    "dbname": os.getenv("DB_NAME"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
    "sslmode": "disable"
}

def get_db_connection():
    return psycopg2.connect(**DB_PARAMS, cursor_factory=psycopg2.extras.DictCursor)

# ---------- Хелперы ----------
def get_active_subscription(client_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT s.*, p.id as plan_id, p.name as plan_name, p.price, p.currency, p.lead_limit, p.features
        FROM subscriptions s
        JOIN plans p ON s.plan_id = p.id
        WHERE s.client_id = %s AND s.status = 'active'
        ORDER BY s.created_at DESC
        LIMIT 1
    """, (client_id,))
    sub = cur.fetchone()
    cur.close()
    conn.close()
    return dict(sub) if sub else None

def get_client_usage(client_id):
    """Возвращает использование лидов и документов за текущий месяц"""
    conn = get_db_connection()
    cur = conn.cursor()
    # Лиды за текущий месяц
    cur.execute("""
        SELECT COUNT(*) FROM leads
        WHERE client_id = %s
        AND created_at >= date_trunc('month', now())
    """, (client_id,))
    leads_count = cur.fetchone()[0] or 0
    # Количество документов (чанков)
    cur.execute("""
        SELECT COUNT(DISTINCT metadata->>'filename')
        FROM documents
        WHERE client_id = %s AND metadata->>'filename' IS NOT NULL
    """, (client_id,))
    docs_count = cur.fetchone()[0] or 0
    cur.close()
    conn.close()
    return {"leads_used": leads_count, "docs_used": docs_count}

def check_auth(required_role='manager'):
    """Проверка авторизации и роли."""
    if not session.get('admin_id'):
        return redirect(url_for('login'))
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT role FROM admins WHERE id = %s", (session['admin_id'],))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        session.clear()
        return redirect(url_for('login'))
    role = row[0]
    if required_role == 'admin' and role != 'admin':
        flash('Недостаточно прав')
        return redirect(url_for('clients'))
    return None

# ---------- Аутентификация ----------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT id, username, password_hash, role FROM admins WHERE username = %s", (username,))
        admin = cur.fetchone()
        cur.close()
        conn.close()
        if admin and check_password_hash(admin['password_hash'], password):
            session['admin_id'] = admin['id']
            session['admin_username'] = admin['username']
            session['admin_role'] = admin['role']
            return redirect(url_for('clients'))
        else:
            flash("Неверный логин или пароль")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ---------- Управление администраторами (только admin) ----------
@app.route("/admins")
def admins_list():
    redirect_resp = check_auth('admin')
    if redirect_resp:
        return redirect_resp
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, username, role, created_at FROM admins ORDER BY username")
    admins = cur.fetchall()
    cur.close()
    conn.close()
    return render_template("admins.html", admins=admins)

@app.route("/admin/add", methods=["GET", "POST"])
def admin_add():
    redirect_resp = check_auth('admin')
    if redirect_resp:
        return redirect_resp
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        role = request.form.get("role", "manager")
        password_hash = generate_password_hash(password)
        conn = get_db_connection()
        cur = conn.cursor()
        try:
            cur.execute("INSERT INTO admins (username, password_hash, role) VALUES (%s, %s, %s)",
                        (username, password_hash, role))
            conn.commit()
            flash("Администратор создан")
        except psycopg2.IntegrityError:
            conn.rollback()
            flash("Пользователь с таким именем уже существует")
        cur.close()
        conn.close()
        return redirect(url_for('admins_list'))
    return render_template("admin_edit.html", admin=None)

@app.route("/admin/<admin_id>", methods=["GET", "POST"])
def admin_edit(admin_id):
    redirect_resp = check_auth('admin')
    if redirect_resp:
        return redirect_resp
    conn = get_db_connection()
    cur = conn.cursor()
    if request.method == "POST":
        username = request.form["username"]
        role = request.form.get("role", "manager")
        if request.form.get("password"):
            password_hash = generate_password_hash(request.form["password"])
            cur.execute("UPDATE admins SET username=%s, password_hash=%s, role=%s WHERE id=%s",
                        (username, password_hash, role, admin_id))
        else:
            cur.execute("UPDATE admins SET username=%s, role=%s WHERE id=%s",
                        (username, role, admin_id))
        conn.commit()
        cur.close()
        conn.close()
        flash("Администратор обновлён")
        return redirect(url_for('admins_list'))
    else:
        cur.execute("SELECT id, username, role FROM admins WHERE id = %s", (admin_id,))
        admin = cur.fetchone()
        cur.close()
        conn.close()
        if not admin:
            abort(404)
        return render_template("admin_edit.html", admin=dict(admin))

@app.route("/admin/<admin_id>/delete", methods=["POST"])
def admin_delete(admin_id):
    redirect_resp = check_auth('admin')
    if redirect_resp:
        return redirect_resp
    if admin_id == session['admin_id']:
        flash("Нельзя удалить свою учётную запись")
        return redirect(url_for('admins_list'))
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM admins WHERE id = %s", (admin_id,))
    conn.commit()
    cur.close()
    conn.close()
    flash("Администратор удалён")
    return redirect(url_for('admins_list'))

# ---------- Клиенты ----------
@app.route("/")
def clients():
    redirect_resp = check_auth('manager')
    if redirect_resp:
        return redirect_resp
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM clients ORDER BY name")
    rows = cur.fetchall()
    cur.close()
    conn.close()

    clients_list = []
    for row in rows:
        client = dict(row)
        client["subscription"] = get_active_subscription(client["id"])
        client["usage"] = get_client_usage(client["id"])
        clients_list.append(client)

    return render_template("clients.html", clients=clients_list)

@app.route("/client/<client_id>", methods=["GET", "POST"])
def client_edit(client_id):
    redirect_resp = check_auth('manager')
    if redirect_resp:
        return redirect_resp
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM clients WHERE id = %s", (client_id,))
    client = cur.fetchone()
    if not client:
        flash("Клиент не найден")
        cur.close()
        conn.close()
        return redirect(url_for("clients"))
    client = dict(client)

    cur.execute("SELECT id, name, price, currency FROM plans WHERE is_active = TRUE ORDER BY name")
    plans = cur.fetchall()

    current_sub = get_active_subscription(client_id)
    usage_stats = get_client_usage(client_id)

    if request.method == "POST":
        # Основные поля
        client_update = {
            "name": request.form["name"],
            "contact_name": request.form["contact_name"],
            "contact_email": request.form["contact_email"],
            "contact_phone": request.form["contact_phone"],
            "is_active": request.form.get("is_active") == "on",
            "bot_token": request.form["bot_token"],
            "system_prompt": request.form.get("system_prompt", ""),
            "bot_name": request.form.get("bot_name", ""),
            "bot_role": request.form.get("bot_role", ""),
            "company_description": request.form.get("company_description", ""),
            "example_questions": request.form.get("example_questions", ""),
        }

        # Формируем crm_config
        crm_config = {}
        if request.form.get("amo_enabled") == "on":
            crm_config["amo"] = {
                "account_key": request.form.get("amo_account_key", ""),
                "enabled": True
            }
        if request.form.get("yougile_enabled") == "on":
            crm_config["yougile"] = {
                "api_token": request.form.get("yougile_api_token", ""),
                "project_id": request.form.get("yougile_project_id", ""),
                "column_id": request.form.get("yougile_column_id", ""),
                "enabled": True
            }
        if request.form.get("bitrix_enabled") == "on":
            crm_config["bitrix24"] = {
                "webhook": request.form.get("bitrix_webhook", ""),
                "enabled": True
            }
        client_update["crm_config"] = Json(crm_config)

        # Формируем notifications
        notifications = {}
        if request.form.get("telegram_notify_enabled") == "on":
            notifications["telegram"] = {
                "chat_id": request.form.get("telegram_chat_id"),
                "enabled": True
            }
        client_update["notifications"] = Json(notifications)

        # Обновление клиента
        set_clause = ", ".join([f"{k} = %s" for k in client_update.keys()])
        values = list(client_update.values()) + [client_id]
        cur.execute(f"UPDATE clients SET {set_clause} WHERE id = %s", values)

        # Подписка
        plan_id = request.form.get("plan_id")
        start_date = request.form.get("start_date")
        end_date = request.form.get("end_date") or None
        status = request.form.get("status", "active")
        auto_renew = request.form.get("auto_renew") == "on"
        setup_fee_paid = request.form.get("setup_fee_paid") == "on"

        # Если дата начала не указана, ставим текущую
        if start_date == '':
            start_date = datetime.now().isoformat()
        # Если дата окончания пустая, передаём None
        if end_date == '':
            end_date = None

        if current_sub:
            cur.execute("""
                UPDATE subscriptions
                SET plan_id = %s, start_date = %s, end_date = %s, status = %s, auto_renew = %s, setup_fee_paid = %s
                WHERE id = %s
            """, (plan_id, start_date, end_date, status, auto_renew, setup_fee_paid, current_sub["id"]))
        else:
            cur.execute("""
                INSERT INTO subscriptions (client_id, plan_id, start_date, end_date, status, auto_renew, setup_fee_paid)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (client_id, plan_id, start_date, end_date, status, auto_renew, setup_fee_paid))

        conn.commit()
        cur.close()
        conn.close()
        flash("Данные клиента сохранены")
        return redirect(url_for("clients"))

    cur.close()
    conn.close()
    return render_template(
        "client_edit.html",
        client=client,
        plans=plans,
        current_sub=current_sub,
        usage_stats=usage_stats
    )

@app.route("/client/add", methods=["GET", "POST"])
def client_add():
    redirect_resp = check_auth('manager')
    if redirect_resp:
        return redirect_resp
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, name, price, currency FROM plans WHERE is_active = TRUE ORDER BY name")
    plans = cur.fetchall()

    if request.method == "POST":
        client_data = {
            "name": request.form["name"],
            "contact_name": request.form["contact_name"],
            "contact_email": request.form["contact_email"],
            "contact_phone": request.form["contact_phone"],
            "is_active": True,
            "bot_token": request.form.get("bot_token", ""),
            "system_prompt": request.form.get("system_prompt", ""),
            "bot_name": request.form.get("bot_name", ""),
            "bot_role": request.form.get("bot_role", ""),
            "company_description": request.form.get("company_description", ""),
            "example_questions": request.form.get("example_questions", ""),
            "crm_config": Json({}),
            "notifications": Json({}),
        }
        columns = list(client_data.keys())
        placeholders = ", ".join(["%s"] * len(columns))
        sql = f"INSERT INTO clients ({', '.join(columns)}) VALUES ({placeholders}) RETURNING id"
        cur.execute(sql, list(client_data.values()))
        client_id = cur.fetchone()[0]

        plan_id = request.form["plan_id"]
        start_date = request.form.get("start_date")
        if not start_date:
            start_date = datetime.now().isoformat()
        end_date = request.form.get("end_date") or None
        status = request.form.get("status", "active")
        auto_renew = request.form.get("auto_renew") == "on"
        setup_fee_paid = request.form.get("setup_fee_paid") == "on"

        cur.execute("""
            INSERT INTO subscriptions (client_id, plan_id, start_date, end_date, status, auto_renew, setup_fee_paid)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (client_id, plan_id, start_date, end_date, status, auto_renew, setup_fee_paid))

        conn.commit()
        cur.close()
        conn.close()
        flash("Клиент создан")
        return redirect(url_for("clients"))

    cur.close()
    conn.close()
    return render_template("client_edit.html",
                           client=None,
                           plans=plans,
                           current_sub=None,
                           usage_stats={"leads_used": 0, "docs_used": 0})

# ---------- Тарифы (Plans) ----------
@app.route("/plans")
def plans_list():
    redirect_resp = check_auth('manager')
    if redirect_resp:
        return redirect_resp
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM plans ORDER BY name")
    plans = cur.fetchall()
    cur.close()
    conn.close()
    return render_template("plans.html", plans=plans)

@app.route("/plan/add", methods=["GET", "POST"])
def plan_add():
    redirect_resp = check_auth('manager')
    if redirect_resp:
        return redirect_resp
    if request.method == "POST":
        name = request.form["name"]
        price = request.form["price"]
        setup_price = request.form.get("setup_price", 0)
        currency = request.form.get("currency", "RUB")
        lead_limit = request.form.get("lead_limit", 0)
        is_active = request.form.get("is_active") == "on"
        features = request.form.get("features", "{}")
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO plans (name, price, setup_price, currency, lead_limit, is_active, features)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (name, price, setup_price, currency, lead_limit, is_active, features))
        conn.commit()
        cur.close()
        conn.close()
        flash("План создан")
        return redirect(url_for("plans_list"))
    return render_template("plan_edit.html", plan=None)

@app.route("/plan/<plan_id>", methods=["GET", "POST"])
def plan_edit(plan_id):
    redirect_resp = check_auth('manager')
    if redirect_resp:
        return redirect_resp
    conn = get_db_connection()
    cur = conn.cursor()
    if request.method == "POST":
        name = request.form["name"]
        price = request.form["price"]
        setup_price = request.form.get("setup_price", 0)
        currency = request.form.get("currency", "RUB")
        lead_limit = request.form.get("lead_limit", 0)
        is_active = request.form.get("is_active") == "on"
        features = request.form.get("features", "{}")
        cur.execute("""
            UPDATE plans
            SET name=%s, price=%s, setup_price=%s, currency=%s, lead_limit=%s, is_active=%s, features=%s
            WHERE id=%s
        """, (name, price, setup_price, currency, lead_limit, is_active, features, plan_id))
        conn.commit()
        cur.close()
        conn.close()
        flash("План обновлён")
        return redirect(url_for("plans_list"))
    else:
        cur.execute("SELECT * FROM plans WHERE id = %s", (plan_id,))
        plan = cur.fetchone()
        cur.close()
        conn.close()
        if not plan:
            abort(404)
        return render_template("plan_edit.html", plan=dict(plan))

@app.route("/plan/<plan_id>/delete", methods=["POST"])
def plan_delete(plan_id):
    redirect_resp = check_auth('manager')
    if redirect_resp:
        return redirect_resp
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id FROM subscriptions WHERE plan_id = %s LIMIT 1", (plan_id,))
    if cur.fetchone():
        flash("Нельзя удалить план, на него есть подписки")
    else:
        cur.execute("DELETE FROM plans WHERE id = %s", (plan_id,))
        conn.commit()
        flash("План удалён")
    cur.close()
    conn.close()
    return redirect(url_for("plans_list"))

# ---------- Документы клиента ----------
@app.route("/client/<client_id>/documents")
def client_documents(client_id):
    redirect_resp = check_auth('manager')
    if redirect_resp:
        return redirect_resp
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT name FROM clients WHERE id = %s", (client_id,))
    client_name = cur.fetchone()
    if not client_name:
        flash("Клиент не найден")
        return redirect(url_for("clients"))
    
    # Получаем все чанки для клиента
    cur.execute("""
        SELECT id, content, metadata, created_at
        FROM documents
        WHERE client_id = %s
        ORDER BY created_at DESC
    """, (client_id,))
    rows = cur.fetchall()
    cur.close()
    conn.close()

    # Группируем по имени файла
    documents_by_file = {}
    for row in rows:
        doc = dict(row)
        filename = doc['metadata'].get('filename', 'Без имени')
        if filename not in documents_by_file:
            documents_by_file[filename] = {
                'filename': filename,
                'chunks': [],
                'first_created': doc['created_at'],
                'chunk_count': 0
            }
        documents_by_file[filename]['chunks'].append(doc)
        documents_by_file[filename]['chunk_count'] += 1
        if doc['created_at'] < documents_by_file[filename]['first_created']:
            documents_by_file[filename]['first_created'] = doc['created_at']

    document_groups = list(documents_by_file.values())
    return render_template("documents.html", client_id=client_id, client_name=client_name[0], document_groups=document_groups)

@app.route("/client/<client_id>/upload", methods=["GET", "POST"])
def upload_document(client_id):
    redirect_resp = check_auth('manager')
    if redirect_resp:
        return redirect_resp
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT name FROM clients WHERE id = %s", (client_id,))
    client_name = cur.fetchone()
    cur.close()
    conn.close()
    if not client_name:
        flash("Клиент не найден")
        return redirect(url_for("clients"))

    if request.method == "POST":
        if 'file' not in request.files:
            flash("Файл не выбран")
            return redirect(request.url)
        file = request.files['file']
        if file.filename == '':
            flash("Файл не выбран")
            return redirect(request.url)

        allowed_extensions = {'.txt', '.pdf'}
        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in allowed_extensions:
            flash("Поддерживаются только .txt и .pdf файлы")
            return redirect(request.url)

        # Сохраняем во временный файл
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
            file.save(tmp.name)
            tmp_path = tmp.name

        # Асинхронная функция ингеста
        async def ingest():
            try:
                get_db_pool()
            except RuntimeError:
                await init_db_pool()
            try:
                pool = get_db_pool()
                logger.info(f"✅ Пул получен: {pool}")
            except Exception as e:
                logger.error(f"❌ Не удалось получить пул после инициализации: {e}")
                raise
            async with aiofiles.open(tmp_path, 'rb') as f:
                content = await f.read()
            class FakeFile:
                def __init__(self, filename, content, content_type):
                    self.filename = filename
                    self.content = content
                    self.content_type = content_type
                async def read(self):
                    return self.content
            fake_file = FakeFile(file.filename, content, file.content_type)
            metadata = {"uploaded_by": session.get('admin_username', 'admin')}
            try:
                result = await process_document(client_id, fake_file, metadata)
                return result
            except Exception as e:
                logger.error(f"Ошибка ингеста: {e}", exc_info=True)
                raise

        try:
            result = loop.run_until_complete(ingest())
            flash(f"Документ загружен, создано {result} чанков")
        except Exception as e:
            flash(f"Ошибка при обработке документа: {str(e)}")
        finally:
            os.unlink(tmp_path)

        return redirect(url_for('client_documents', client_id=client_id))

    return render_template("upload_document.html", client_id=client_id, client_name=client_name[0])

# ---------- Удаление документа по имени файла ----------
@app.route("/client/<client_id>/delete_document_by_filename", methods=["POST"])
def delete_document_by_filename(client_id):
    redirect_resp = check_auth('manager')
    if redirect_resp:
        return redirect_resp
    filename = request.form.get('filename')
    if not filename:
        flash("Не указано имя файла")
        return redirect(url_for('client_documents', client_id=client_id))
    
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        DELETE FROM documents
        WHERE client_id = %s AND metadata->>'filename' = %s
    """, (client_id, filename))
    deleted = cur.rowcount
    conn.commit()
    cur.close()
    conn.close()
    
    flash(f"Удалено {deleted} чанков документа «{filename}»")
    return redirect(url_for('client_documents', client_id=client_id))

# ---------- Логи ----------
@app.route("/logs")
def logs():
    redirect_resp = check_auth('manager')
    if redirect_resp:
        return redirect_resp
    client_filter = request.args.get('client_id', '')
    conn = get_db_connection()
    cur = conn.cursor()
    # Список клиентов для фильтра
    cur.execute("SELECT id, name FROM clients ORDER BY name")
    clients_list = cur.fetchall()
    if client_filter:
        cur.execute("""
            SELECT ul.*, c.name as client_name
            FROM usage_logs ul
            LEFT JOIN clients c ON ul.client_id = c.id
            WHERE ul.client_id = %s
            ORDER BY ul.event_date DESC
            LIMIT 200
        """, (client_filter,))
    else:
        cur.execute("""
            SELECT ul.*, c.name as client_name
            FROM usage_logs ul
            LEFT JOIN clients c ON ul.client_id = c.id
            ORDER BY ul.event_date DESC
            LIMIT 200
        """)
    logs = cur.fetchall()
    cur.close()
    conn.close()
    return render_template("logs.html", logs=logs, clients=clients_list, selected_client=client_filter)

# ---------- Глобальный цикл событий и инициализация пула ----------
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)
try:
    loop.run_until_complete(init_db_pool())
    logger.info("✅ Пул БД инициализирован в глобальном цикле")
except Exception as e:
    logger.error(f"❌ Ошибка инициализации пула БД: {e}", exc_info=True)

if __name__ == "__main__":
    app.run(debug=True, port=5000)