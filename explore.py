import requests
import os
import config
from dotenv import load_dotenv

load_dotenv()

URL = config.TRIP_UPDATES_URL
SUB_KEY = os.environ["AT_SUB_KEY"]

raw_resp= requests.get(URL, headers = {"Ocp-Apim-Subscription-Key": SUB_KEY})
print("Status Code:", raw_resp.status_code)

data = raw_resp.json()
response = data["response"]
print("Keys inside the response: ", response.keys())
print("Headers: ", response["header"])

entities = response["entity"]
print("First Entity: ", entities[0])