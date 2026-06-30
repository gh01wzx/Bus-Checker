import requests
import os
import config
import statistics
import datetime
import duckdb
import pandas as pd
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
current_timestamp = datetime.datetime.now()

rows = []
for trip in entities:
    tu = trip["trip_update"]
    delay = tu.get("delay")

    if delay is None or abs(delay) > MAX_DELAY:  # filter out dirty ones
        continue

    rows.append(
        {
            "captured_at": current_timestamp,
            "route_id": tu["trip"]["route_id"],
            "trip_id": tu["trip"]["trip_id"],
            "delay": delay,
        }
    )

trip_punctuality_df = pd.DataFrame(rows)
db_con = duckdb.connect("bus_data.duckdb")

db_con.execute("""
    CREATE TABLE IF NOT EXISTS trip_punctuality (
        captured_at  TIMESTAMP,
        route_id     VARCHAR,
        trip_id      VARCHAR,
        delay        INTEGER
    )
""")

db_con.execute("INSERT INTO trip_punctuality SELECT * FROM trip_punctuality_df")
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
            "consistency_sec": (
                round(statistics.stdev(delays), 2) if len(delays) > 1 else 0
            ),
        }
    )

summary.sort(key=lambda x: x["avg_delay_sec"], reverse=True)

ON_TIME_EARLY = -60
ON_TIME_LATE = 5 * 60

delays = [row["delay"] for row in rows]
on_time = [d for d in delays if ON_TIME_EARLY <= d <= ON_TIME_LATE]
on_time_rate = len(on_time) / len(delays)
all_routes_avg_delay = sum(delays) / len(delays)
all_routes_median_delay = statistics.median(delays)
early = [d for d in delays if d < ON_TIME_EARLY]
late = [d for d in delays if d > ON_TIME_LATE]
late_routes = [s for s in summary if s["avg_delay_sec"] > 0]
early_routes = [s for s in summary if s["avg_delay_sec"] < 0]
late_routes_percentage = len(late_routes) / len(summary) * 100
early_routes_percentage = len(early_routes) / len(summary) * 100

print(f"On time rate: {on_time_rate*100:.2f}%")
print(f"Average delays(whole network): {all_routes_avg_delay:.2f} seconds")
print(f"Median delays(whole network): {all_routes_median_delay} seconds")
print(f"Number of bus running early(whole network): {len(early)}")
print(f"Number of bus running on time(whole network): {len(on_time)}")
print(f"Number of bus running late(whole network): {len(late)}")
print(f"Worst 3 routes by average delay: ")
for route in summary[:3]:
    print(
        f"Route id: {route['route_id']} Average delay: {route['avg_delay_sec']} Trip count: {route['trip_count']}"
    )
print(f"{late_routes_percentage:.2f}% routes running late")
print(f"{early_routes_percentage:.2f}% routes running early")

summary.sort(key=lambda x: x["consistency_sec"], reverse=True)

print(f"Worst 3 routes by delay consistency: ")
for route in summary[:3]:
    print(
        f"Route id: {route['route_id']} Average delay: {route['avg_delay_sec']} Trip count: {route['trip_count']} Consistency in seconds(std): {route['consistency_sec']}"
    )
