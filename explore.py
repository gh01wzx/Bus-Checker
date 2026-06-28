import requests
import os
from dotenv import load_dotenv

load_dotenv()

URL = "https://api.at.govt.nz/realtime/legacy/vehiclelocations"
SUB_KEY = os.environ["AT_SUB_KEY"]

raw_resp= requests.get(URL, headers = {"Ocp-Apim-Subscription-Key": SUB_KEY})
print("Status Code:", raw_resp.status_code)

data = raw_resp.json()
response = data["response"]
print("Keys inside the response: ", response.keys())