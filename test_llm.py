import asyncio
from services.deepseek import ask_with_rag


async def test():
    reply, _ = await ask_with_rag("Привет")
    print(reply)


asyncio.run(test())
