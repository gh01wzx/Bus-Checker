import requests
import os
import config
from collections import defaultdict
from dotenv import load_dotenv

load_dotenv()

URL = config.TRIP_UPDATES_URL
SUB_KEY = os.environ["AT_SUB_KEY"]
MAX_DELAY = 15 * 60

raw_resp = requests.get(URL, headers={"Ocp-Apim-Subscription-Key": SUB_KEY})

if raw_resp.status_code != 200:
    print(f"Request failed with status {raw_resp.status_code}")
    print(raw_resp.text[:300])
    raise SystemExit(1)

data = raw_resp.json()
entities = data["response"]["entity"]

print("Number of trips:", len(entities))

rows = []
for trip in entities:
    tu = trip["trip_update"]
    delay = tu.get("delay")

    if delay is None or abs(delay) > MAX_DELAY:  # filter out dirty ones
        continue

    rows.append(
        {
            "route_id": tu["trip"]["route_id"],
            "delay": delay,
        }
    )


by_route = defaultdict(list)

for row in rows:
    by_route[row["route_id"]].append(row["delay"])

summary = []

for route_id, delays in by_route.items():
    avg_delay = sum(delays) / len(delays)
    summary.append(
        {
            "route_id": route_id,
            "avg_delay_sec": round(avg_delay, 2),
            "trip_count": len(delays),
        }
    )

summary.sort(key=lambda x: x["avg_delay_sec"], reverse=True)
