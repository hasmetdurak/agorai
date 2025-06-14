import os
import asyncio
import httpx
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, Column, Integer, String, DateTime, func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime, timedelta
import redis.asyncio as redis # Redis'i async olarak import ediyoruz
from dotenv import load_dotenv
import hashlib # IP hashlemek için

# .env dosyasındaki değişkenleri yükle
load_dotenv()

# --- Ortam Değişkenleri --- (Render'da ayarlanacak)
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:password@host:port/database")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
# Grok ve Gemini için API anahtarları ve endpoint'ler güncellenmeli
GROK_API_KEY = os.getenv("GROK_API_KEY") # Gerçek anahtarınızı kullanın
GEMINI_API_KEY_1 = os.getenv("GEMINI_API_KEY_1") # Gerçek anahtarınızı kullanın
GEMINI_API_KEY_2 = os.getenv("GEMINI_API_KEY_2") # Gerçek anahtarınızı kullanın

# --- FastAPI Uygulaması --- 
app = FastAPI(title="AgorAi Backend")

# --- CORS Ayarları --- (Netlify frontend'inizden gelen isteklere izin verin)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] # Geliştirme için *, canlıda Netlify URL'nizi ekleyin
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"]
)

# --- Veritabanı Ayarları (SQLAlchemy) --- 
Base = declarative_base()

class UserQuery(Base):
    __tablename__ = "user_queries"
    id = Column(Integer, primary_key=True, index=True)
    hashed_ip = Column(String, index=True) # IP adresinin hash'lenmiş hali
    query_count = Column(Integer, default=0)
    last_query_date = Column(DateTime, default=func.now())

engine = create_engine(DATABASE_URL)
Base.metadata.create_all(bind=engine) # Tabloları oluştur (eğer yoksa)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# --- Redis Cache Ayarları --- 
redis_client = None

@app.on_event("startup")
async def startup_event():
    global redis_client
    try:
        redis_client = await redis.from_url(REDIS_URL, encoding="utf-8", decode_responses=True)
        await redis_client.ping() # Bağlantıyı test et
        print("Redis'e başarıyla bağlanıldı.")
    except Exception as e:
        print(f"Redis bağlantı hatası: {e}")
        redis_client = None # Bağlantı başarısız olursa None olarak ayarla

@app.on_event("shutdown")
async def shutdown_event():
    if redis_client:
        await redis_client.close()
        print("Redis bağlantısı kapatıldı.")

# --- Yardımcı Fonksiyonlar --- 
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def hash_ip(ip_address: str) -> str:
    return hashlib.sha256(ip_address.encode('utf-8')).hexdigest()

async def get_cached_response(query: str):
    if not redis_client:
        return None
    try:
        cached = await redis_client.get(f"query_cache:{query.lower().strip()}")
        return cached # JSON string olarak dönecek
    except Exception as e:
        print(f"Redis get hatası: {e}")
        return None

async def set_cached_response(query: str, response_data: str):
    if not redis_client:
        return
    try:
        # Cache süresini 1 saat olarak ayarlayalım (3600 saniye)
        await redis_client.setex(f"query_cache:{query.lower().strip()}", 3600, response_data)
    except Exception as e:
        print(f"Redis set hatası: {e}")

# --- Kota Kontrol Middleware --- 
MAX_QUERIES_PER_DAY = 10

@app.middleware("http")
async def quota_check_middleware(request: Request, call_next):
    if request.url.path == "/query": # Sadece /query endpoint'i için kota kontrolü
        client_ip = request.client.host
        hashed_client_ip = hash_ip(client_ip)
        
        db = SessionLocal()
        try:
            user_query_record = db.query(UserQuery).filter(UserQuery.hashed_ip == hashed_client_ip).first()
            
            today = datetime.utcnow().date()

            if user_query_record:
                # Eğer son sorgu tarihi bugünden eskiyse, sayacı sıfırla
                if user_query_record.last_query_date.date() < today:
                    user_query_record.query_count = 0
                    user_query_record.last_query_date = datetime.utcnow()
                
                if user_query_record.query_count >= MAX_QUERIES_PER_DAY:
                    raise HTTPException(status_code=429, detail="Günlük sorgu limitine ulaşıldı.")
                
                # Bu satırı /query endpoint'ine taşıyacağız, çünkü başarılı yanıttan sonra artmalı
                # user_query_record.query_count += 1 
                # user_query_record.last_query_date = datetime.utcnow()
            else:
                # İlk defa sorgu yapıyorsa yeni kayıt oluştur
                user_query_record = UserQuery(hashed_ip=hashed_client_ip, query_count=0, last_query_date=datetime.utcnow())
                db.add(user_query_record)
            
            # Değişiklikleri kaydet (eğer varsa)
            db.commit()
            # db.refresh(user_query_record) # Bu satıra gerek yok, çünkü sayacı /query içinde artıracağız

        finally:
            db.close()
    
    response = await call_next(request)
    return response

# --- AI API Çağrıları --- 
async def fetch_openai(session, query):
    if not OPENAI_API_KEY:
        return {"model": "chatgpt", "error": "OpenAI API anahtarı ayarlanmamış."}
    url = "https://api.openai.com/v1/chat/completions" # Güncel endpoint
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}"}
    payload = {"model": "gpt-3.5-turbo", "messages": [{"role": "user", "content": query}]}
    try:
        response = await session.post(url, headers=headers, json=payload, timeout=20)
        response.raise_for_status()
        return {"model": "chatgpt", "response": response.json()["choices"][0]["message"]["content"]}
    except Exception as e:
        return {"model": "chatgpt", "error": str(e)}

async def fetch_grok(session, query):
    # TODO: Grok API endpoint ve payload formatını güncelle
    if not GROK_API_KEY:
        return {"model": "grok", "error": "Grok API anahtarı ayarlanmamış."}
    # Örnek (gerçek endpoint ve payload farklı olabilir):
    # url = "https://api.x.ai/v1/grok/completions" 
    # headers = {"Authorization": f"Bearer {GROK_API_KEY}"}
    # payload = {"prompt": query, "model": "grok-1"}
    # try:
    #     response = await session.post(url, headers=headers, json=payload, timeout=20)
    #     response.raise_for_status()
    #     return {"model": "grok", "response": response.json().get("choices")[0].get("text")}
    # except Exception as e:
    #     return {"model": "grok", "error": str(e)}
    return {"model": "grok", "error": "Grok API entegrasyonu henüz tamamlanmadı."}

async def fetch_gemini(session, query):
    # TODO: Gemini API endpoint ve payload formatını güncelle
    if not GEMINI_API_KEY_1: # Sadece bir anahtar kontrolü yeterli
        return {"model": "gemini", "error": "Gemini API anahtarı ayarlanmamış."}
    # Örnek (gerçek endpoint ve payload farklı olabilir):
    # url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent?key={GEMINI_API_KEY_1}"
    # payload = {"contents":[{"parts":[{"text": query}]}]}
    # try:
    #     response = await session.post(url, json=payload, timeout=20)
    #     response.raise_for_status()
    #     # Gemini yanıt formatı farklı olabilir, doğru şekilde parse edin
    #     return {"model": "gemini", "response": response.json().get("candidates")[0].get("content").get("parts")[0].get("text")}
    # except Exception as e:
    #     return {"model": "gemini", "error": str(e)}
    return {"model": "gemini", "error": "Gemini API entegrasyonu henüz tamamlanmadı."}

async def fetch_deepseek(session, query):
    if not DEEPSEEK_API_KEY:
        return {"model": "deepseek", "error": "DeepSeek API anahtarı ayarlanmamış."}
    url = "https://api.deepseek.com/v1/chat/completions" # DeepSeek API endpoint'i
    headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}"}
    payload = {"model": "deepseek-chat", "messages": [{"role": "user", "content": query}]}
    try:
        response = await session.post(url, headers=headers, json=payload, timeout=20)
        response.raise_for_status()
        return {"model": "deepseek", "response": response.json()["choices"][0]["message"]["content"]}
    except Exception as e:
        return {"model": "deepseek", "error": str(e)}

# --- API Endpoints --- 
@app.get("/health")
async def health_check():
    return {"status": "healthy"}

from pydantic import BaseModel
class QueryRequest(BaseModel):
    query: str

@app.post("/query")
async def process_query(query_request: QueryRequest, request: Request):
    user_query = query_request.query
    client_ip = request.client.host
    hashed_client_ip = hash_ip(client_ip)

    # Cache kontrolü
    cached_data_str = await get_cached_response(user_query)
    if cached_data_str:
        import json
        # Kota artırımını burada da yapmamız gerekebilir, cache'den dönse bile bir sorgu sayılır.
        # Ancak, eğer cache'den dönen sorgular kotadan sayılmayacaksa, aşağıdaki blok kaldırılabilir.
        db = SessionLocal()
        try:
            user_record = db.query(UserQuery).filter(UserQuery.hashed_ip == hashed_client_ip).first()
            if user_record:
                if user_record.last_query_date.date() < datetime.utcnow().date():
                    user_record.query_count = 1
                else:
                    user_record.query_count += 1
                user_record.last_query_date = datetime.utcnow()
                db.commit()
            else: # Normalde middleware'de oluşturulmuş olmalı, ama bir güvenlik önlemi
                new_record = UserQuery(hashed_ip=hashed_client_ip, query_count=1, last_query_date=datetime.utcnow())
                db.add(new_record)
                db.commit()
        finally:
            db.close()
        return {"responses": json.loads(cached_data_str), "source": "cache"}

    # Kota kontrolü (middleware'de yapıldı, burada sadece sayacı artıracağız)
    db = SessionLocal()
    try:
        user_query_record = db.query(UserQuery).filter(UserQuery.hashed_ip == hashed_client_ip).first()
        # Middleware zaten var olmayan kullanıcı için kayıt oluşturmuş veya mevcut kaydı güncellemiş olmalı.
        # Eğer bir şekilde kayıt yoksa (beklenmedik durum), hata dönebiliriz veya yeni kayıt oluşturabiliriz.
        if not user_query_record:
             # Bu durum normalde olmamalı, middleware'in halletmesi gerekir.
             # Güvenlik için burada da bir kontrol eklenebilir veya hata döndürülebilir.
            user_query_record = UserQuery(hashed_ip=hashed_client_ip, query_count=1, last_query_date=datetime.utcnow())
            db.add(user_query_record)
        else:
            if user_query_record.last_query_date.date() < datetime.utcnow().date():
                user_query_record.query_count = 1 # Gün değiştiyse sıfırla ve 1 yap
            else:
                user_query_record.query_count += 1
            user_query_record.last_query_date = datetime.utcnow()
        
        db.commit()
    finally:
        db.close()

    async with httpx.AsyncClient() as session:
        tasks = [
            fetch_openai(session, user_query),
            fetch_grok(session, user_query),
            fetch_gemini(session, user_query),
            fetch_deepseek(session, user_query)
        ]
        results = await asyncio.gather(*tasks)
    
    # Başarılı yanıtları cache'le (JSON string olarak)
    import json
    await set_cached_response(user_query, json.dumps(results))
    
    return {"responses": results, "source": "api"}

# Uygulamayı çalıştırmak için (Render bunu kendi yönetir, lokal test için):
# if __name__ == "__main__":
#     import uvicorn
#     uvicorn.run(app, host="0.0.0.0", port=8000)