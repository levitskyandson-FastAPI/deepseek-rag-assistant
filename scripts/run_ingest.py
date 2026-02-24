import asyncio
from services.ingest_client_docs import ingest_client_folder

CLIENT_ID = "4c019799-2c8b-40d3-9966-589097810e99"
FOLDER_NAME = "feedtech"

if __name__ == "__main__":
    asyncio.run(
        ingest_client_folder(
            CLIENT_ID,
            FOLDER_NAME,
        )
    )