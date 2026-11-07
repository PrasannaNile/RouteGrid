
import os
import requests
from dotenv import load_dotenv
from models import Question, DecisionPayload

load_dotenv()

API_KEY = os.getenv("API_KEY")



if not API_KEY:
    raise ValueError("API_KEY not found in .env")


payload = DecisionPayload(
    state="My payment has failed!",
    questions={
        "is_urgent": Question(
            type="noul",
            instructions="Is this urgent?",
            criteria={
                "true": "Urgent",
                "false": "Not urgent"
            }
        )
    }
)


response = requests.post(
    "https://openrouter.ai/api/alpha/decisions",
    headers={
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    },
    json=payload.to_dict(),
    timeout=30
)

response.raise_for_status()

answers = response.json()["answers"]
print(answers)
