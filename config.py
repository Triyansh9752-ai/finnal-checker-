import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
API_URL = os.getenv("API_URL", "https://huihui.42web.io/api.php?cc=")
MAX_THREADS = int(os.getenv("MAX_THREADS", "5"))
ALLOWED_USERS = set()

