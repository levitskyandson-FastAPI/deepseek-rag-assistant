import requests
from config import settings

API_KEY = settings.deepseek_api_key
url = "https://api.deepseek.com/chat/completions"

headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {API_KEY}"
}

data = {
    "model": "deepseek-chat",
    "messages": [
        {"role": "system", "content": "Ты — ИИ-ассистент агентства Levitsky & Son."},
        {"role": "user", "content": "Привет! Расскажи о себе в двух словах."}
    ],
    "stream": False
}

print("🔄 Отправляю запрос к DeepSeek...")
response = requests.post(url, headers=headers, json=data)

if response.status_code == 200:
    result = response.json()
    answer = result['choices'][0]['message']['content']
    print("✅ УСПЕХ! Ответ от DeepSeek:\n")
    print(answer)
else:
    print(f"❌ ОШИБКА {response.status_code}: {response.text}")