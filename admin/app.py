import os
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, flash
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "supersecretkey")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


def get_active_subscription(client_id):
    sub = (
        supabase.table("subscriptions")
        .select("*, plans(*)")
        .eq("client_id", client_id)
        .eq("status", "active")
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    return sub.data[0] if sub.data else None


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form["password"] == ADMIN_PASSWORD:
            session["admin"] = True
            return redirect(url_for("clients"))
        else:
            flash("Неверный пароль")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.pop("admin", None)
    return redirect(url_for("login"))


@app.route("/")
def clients():
    if not session.get("admin"):
        return redirect(url_for("login"))
    resp = supabase.table("clients").select("*").execute()
    clients_list = resp.data
    for client in clients_list:
        client["subscription"] = get_active_subscription(client["id"])
    return render_template("clients.html", clients=clients_list)


@app.route("/client/<client_id>", methods=["GET", "POST"])
def client_edit(client_id):
    if not session.get("admin"):
        return redirect(url_for("login"))
    client_resp = supabase.table("clients").select("*").eq("id", client_id).execute()
    if not client_resp.data:
        flash("Клиент не найден")
        return redirect(url_for("clients"))
    client = client_resp.data[0]

    plans_resp = supabase.table("plans").select("*").eq("is_active", True).execute()
    plans = plans_resp.data

    current_sub = get_active_subscription(client_id)

    if request.method == "POST":
        client_update = {
            "name": request.form["name"],
            "contact_name": request.form["contact_name"],
            "contact_email": request.form["contact_email"],
            "contact_phone": request.form["contact_phone"],
            "is_active": request.form.get("is_active") == "on",
            "bot_token": request.form["bot_token"],
            "crm_settings": request.form.get("crm_settings", "{}"),
        }
        supabase.table("clients").update(client_update).eq("id", client_id).execute()

        plan_id = request.form.get("plan_id")
        start_date = request.form.get("start_date")
        end_date = request.form.get("end_date") or None
        status = request.form.get("status", "active")
        auto_renew = request.form.get("auto_renew") == "on"

        if current_sub:
            sub_update = {
                "plan_id": plan_id,
                "start_date": start_date,
                "end_date": end_date,
                "status": status,
                "auto_renew": auto_renew,
            }
            supabase.table("subscriptions").update(sub_update).eq(
                "id", current_sub["id"]
            ).execute()
        else:
            new_sub = {
                "client_id": client_id,
                "plan_id": plan_id,
                "start_date": start_date,
                "end_date": end_date,
                "status": status,
                "auto_renew": auto_renew,
            }
            supabase.table("subscriptions").insert(new_sub).execute()

        flash("Данные клиента сохранены")
        return redirect(url_for("clients"))

    return render_template(
        "client_edit.html", client=client, plans=plans, current_sub=current_sub
    )


@app.route("/client/add", methods=["GET", "POST"])
def client_add():
    if not session.get("admin"):
        return redirect(url_for("login"))
    plans_resp = supabase.table("plans").select("*").eq("is_active", True).execute()
    plans = plans_resp.data

    if request.method == "POST":
        client_data = {
            "name": request.form["name"],
            "contact_name": request.form["contact_name"],
            "contact_email": request.form["contact_email"],
            "contact_phone": request.form["contact_phone"],
            "is_active": True,
            "bot_token": request.form["bot_token"],
            "crm_settings": request.form.get("crm_settings", "{}"),
        }
        client_resp = supabase.table("clients").insert(client_data).execute()
        if not client_resp.data:
            flash("Ошибка при создании клиента")
            return redirect(url_for("client_add"))
        client_id = client_resp.data[0]["id"]

        plan_id = request.form["plan_id"]
        start_date = request.form.get("start_date")
        if not start_date:
            start_date = datetime.now().isoformat()
        end_date = request.form.get("end_date") or None
        status = request.form.get("status", "active")
        auto_renew = request.form.get("auto_renew") == "on"

        sub_data = {
            "client_id": client_id,
            "plan_id": plan_id,
            "start_date": start_date,
            "end_date": end_date,
            "status": status,
            "auto_renew": auto_renew,
        }
        supabase.table("subscriptions").insert(sub_data).execute()

        flash("Клиент и подписка созданы")
        return redirect(url_for("clients"))

    return render_template(
        "client_edit.html", client=None, plans=plans, current_sub=None
    )


@app.route("/plans")
def plans():
    if not session.get("admin"):
        return redirect(url_for("login"))
    resp = supabase.table("plans").select("*").execute()
    return render_template("plans.html", plans=resp.data)


@app.route("/logs")
def logs():
    if not session.get("admin"):
        return redirect(url_for("login"))
    resp = (
        supabase.table("usage_logs")
        .select("*, clients(name)")
        .order("event_date", desc=True)
        .limit(100)
        .execute()
    )
    return render_template("logs.html", logs=resp.data)


if __name__ == "__main__":
    app.run(debug=True, port=5000)
