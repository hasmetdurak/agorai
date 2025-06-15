import redis
import os
import json
from fastapi import FastAPI, Request
from hashlib import md5
import requests
from sqlalchemy import create_engine, text
from datetime import datetime

app = FastAPI()

DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_engine(DATABASE_URL)

REDIS_URL = os.getenv("REDIS_URL")
redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True, ssl=True)

def cache_response(query: str, responses: dict):
    query_hash = md5(query.encode()).hexdigest()
    redis_client.setex(f"query:{query_hash}", 3600, json.dumps(responses))

def get_cached_response(query: str):
    query_hash = md5(query.encode()).hexdigest()
    cached = redis_client.get(f"query:{query_hash}")
    return json.loads(cached) if cached else None

def check_quota(ip_address: str):
    with engine.connect() as conn:
        result = conn.execute(
            text("SELECT query_count, last_query_date FROM user_queries WHERE ip_address = :ip"),
            {"ip": ip_address}
        ).fetchone()
        today = datetime.now().date()
        if result:
            query_count, last_date = result
            if last_date == today and query_count >= 10:
                return False, "Günlük 10 sorgu limitine ulaştınız."
            elif last_date != today:
                conn.execute(
                    text("UPDATE user_queries SET query_count = 1, last_query_date = :today WHERE ip_address = :ip"),
                    {"today": today, "ip": ip_address}
                )
                conn.commit()
                return True, ""
            else:
                conn.execute(
                    text("UPDATE user_queries SET query_count = query_count + 1 WHERE ip_address = :ip"),
                    {"ip": ip_address}
                )
                conn.commit()
                return True, ""
        else:
            conn.execute(
                text("INSERT INTO user_queries (ip_address, query_count, last_query_date) VALUES (:ip, 1, :today)"),
                {"ip": ip_address, "today": today}
            )
            conn.commit()
            return True, ""

@app.post("/query")
async def handle_query(request: Request, query: dict):
    question = query.get("query")
    ip_address = request.client.host

    allowed, message = check_quota(ip_address)
    if not allowed:
        return {"error": message}

    cached = get_cached_response(question)
    if cached:
        return cached

    responses = {
        "chatgpt": "Merhaba, bu bir örnek yanıt!",
        "grok": "Selam, ben Grok’tan yanıt veriyorum!"
    }

    cache_response(question, responses)
    return responses

@app.get("/health")
async def health_check():
    return {"status": "OK"}
