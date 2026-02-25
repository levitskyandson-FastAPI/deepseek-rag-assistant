import os
import json
import time
import requests
from dotenv import load_dotenv
print("🔥 AMOCRM FILE LOADED")

load_dotenv()

# ==========================================================
# 🔐 MULTI-TENANT CONFIG
# ==========================================================

ACCOUNTS_RAW = os.getenv("AMO_ACCOUNTS_JSON")

if not ACCOUNTS_RAW:
    ACCOUNTS = {}
else:
    try:
        ACCOUNTS = json.loads(ACCOUNTS_RAW)
    except Exception as e:
        raise ValueError(f"AMO_ACCOUNTS_JSON поврежден: {e}")

# ==========================================================
# 🧠 CUSTOM FIELD IDS (ЛИД)
# ==========================================================

FIELD_IDS = {
    "problem": 1281927,
    "goal": 1281933,
    "volume": 1281937,
    "meeting_time": 1281943,
    "sphere": 1283649,
   
}

# ==========================================================
# 🔧 CORE CLASS
# ==========================================================

class AmoCRM:

    def __init__(self, account_key: str):

        if not ACCOUNTS:
            raise ValueError("AMO_ACCOUNTS_JSON пуст")

        if account_key not in ACCOUNTS:
            raise ValueError(f"AmoCRM аккаунт '{account_key}' не найден")

        account = ACCOUNTS[account_key]

        self.token = account["access_token"]
        self.api_domain = account["api_domain"]
        self.pipeline_id = account.get("pipeline_id", 0)

        self.base_url = f"https://{self.api_domain}/api/v4"

        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    # ======================================================
    # UTILS
    # ======================================================

    def _now(self):
        return int(time.time())

    def _cf(self, field_key: str, value):
        if not value:
            return None

        return {
            "field_id": FIELD_IDS[field_key],
            "values": [{"value": str(value)}],
        }
    def _parse_price(self, value):
            

        if not value:
            return 0
            
        digits = "".join(filter(str.isdigit, str(value)))

        return int(digits) if digits else 0

    # ======================================================
    # CONTACTS
    # ======================================================

    def find_contact_by_phone(self, phone: str):

        r = requests.get(
            f"{self.base_url}/contacts",
            headers=self.headers,
            params={"query": phone},
        )

        if r.status_code != 200:
            return None

        contacts = r.json().get("_embedded", {}).get("contacts", [])

        if not contacts:
            return None

        return contacts[0]["id"]

    def create_or_update_contact(self, name, phone, position):

        contact_id = self.find_contact_by_phone(phone)

        custom_fields = [
            {
                "field_code": "PHONE",
                "values": [{"value": phone}],
            }
        ]

        # ✅ Должность (кастомное поле)
        if position:
            custom_fields.append({
                "field_id": 1270425,  # Должность
                "values": [{"value": str(position)}],
            })

        # -----------------------------
        # ОБНОВЛЕНИЕ существующего контакта
        # -----------------------------
        if contact_id:

            payload = {
                "name": name,
                "custom_fields_values": custom_fields
            }

            r = requests.patch(
                f"{self.base_url}/contacts/{contact_id}",
                headers=self.headers,
                json=payload,
            )

            r.raise_for_status()
            return contact_id

        # -----------------------------
        # СОЗДАНИЕ нового контакта
        # -----------------------------
        payload = [
            {
                "name": name,
                "custom_fields_values": custom_fields,
            }
        ]

        r = requests.post(
            f"{self.base_url}/contacts",
            headers=self.headers,
            json=payload,
        )

        r.raise_for_status()

        return r.json()["_embedded"]["contacts"][0]["id"]


    def update_contact_phone(self, contact_id: int, phone: str):

        payload = {
            "custom_fields_values": [
                {
                    "field_code": "PHONE",
                    "values": [{"value": phone}],
                }
            ]
        }

        r = requests.patch(
            f"{self.base_url}/contacts/{contact_id}",
            headers=self.headers,
            json=payload,
        )

        r.raise_for_status()

    # ======================================================
    # COMPANIES
    # ======================================================

    def find_company(self, name):

        r = requests.get(
            f"{self.base_url}/companies",
            headers=self.headers,
            params={"query": name},
        )

        if r.status_code != 200:
            return None

        companies = r.json().get("_embedded", {}).get("companies", [])

        if not companies:
            return None

        return companies[0]["id"]

    def create_or_get_company(self, name):

        company_id = self.find_company(name)

        if company_id:
            return company_id

        payload = [{"name": name}]

        r = requests.post(
            f"{self.base_url}/companies",
            headers=self.headers,
            json=payload,
        )

        r.raise_for_status()

        return r.json()["_embedded"]["companies"][0]["id"]

    # ======================================================
    # LEADS
    # ======================================================

    def create_lead(self, data: dict):

        # 1️⃣ создаём или обновляем контакт
        contact_id = self.create_or_update_contact(
            name=data["name"],
            phone=data["phone"],
            position=data.get("position")
            
        )

        # 2️⃣ создаём компанию (если есть)
        company_id = None
        if data.get("company"):
            company_id = self.create_or_get_company(data["company"])

            if company_id:
                # 🔗 связываем компанию с контактом
                r = requests.post(
                    f"{self.base_url}/contacts/{contact_id}/link",
                    headers=self.headers,
                    json=[{
                        "to_entity_id": company_id,
                        "to_entity_type": "companies"
                    }]
                )
                r.raise_for_status()

        # 3️⃣ custom fields лида
        custom_fields = list(
            filter(
                None,
                [
                    self._cf("problem", data.get("problem")),
                    self._cf("goal", data.get("goal")),
                    self._cf("volume", data.get("volume")),
                    self._cf("meeting_time", data.get("meeting_time")),
                    self._cf("sphere", data.get("sphere")),
                    
                ],
            )
        )

        # 4️⃣ связи лида
        embedded = {"contacts": [{"id": contact_id}]}

        if company_id:
            embedded["companies"] = [{"id": company_id}]

        # 5️⃣ создаём лид
        payload = [
            {
                "name": f"Lead from {data['name']}",
                "created_at": self._now(),
                "pipeline_id": self.pipeline_id,
                "price": self._parse_price(data.get("budget")),  # ← системный бюджет
                "_embedded": embedded,
                "custom_fields_values": custom_fields,
            }
        ]

        r = requests.post(
            f"{self.base_url}/leads",
            headers=self.headers,
            json=payload,
        )

        r.raise_for_status()

        lead_id = r.json()["_embedded"]["leads"][0]["id"]

        return {
            "contact_id": contact_id,
            "lead_id": lead_id,
        }