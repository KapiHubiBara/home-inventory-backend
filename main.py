# ==========================================
# 1. IMPORTY
# ==========================================
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
import os
import jwt
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, status, Query, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field
from passlib.context import CryptContext
import httpx

load_dotenv()

app = FastAPI(title="Home Inventory API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================================
# 2. BAZA DANYCH & BEZPIECZEŃSTWO
# ==========================================
MONGO_URI = os.getenv("MONGO_URI")
DB_NAME = os.getenv("DB_NAME", "home_inventory")
SECRET_KEY = os.getenv("SECRET_KEY", "twoj_super_tajny_klucz_jwt_12345")
ALGORITHM = "HS256"

client = AsyncIOMotorClient(MONGO_URI)
db = client[DB_NAME]

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(days=30))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


async def get_current_user(authorization: Optional[str] = Header(None)) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Brak lub nieprawidłowy token autoryzacyjny")
    token = authorization.split(" ")[1]
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Nieprawidłowy token")
        return username
    except jwt.PyJWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sesja wygasła lub jest niepoprawna")


# ==========================================
# 3. MODELE DANYCH
# ==========================================
class UserAuthSchema(BaseModel):
    username: str
    password: str


class ItemSchema(BaseModel):
    name: str = Field(..., examples=["Mleko 3.2%"])
    barcode: Optional[str] = Field(None)
    brand: Optional[str] = Field(None)
    quantity: float = Field(default=1.0, ge=0.0)
    unit: str = Field(default="szt")
    location: str = Field(default="Spiżarnia")
    category: Optional[str] = Field(default="inne")
    status: Optional[str] = Field(default="w_magazynie")
    expiry_date: Optional[str] = Field(None)
    notes: Optional[str] = Field(None)
    image_url: Optional[str] = Field(None)


class DeductSchema(BaseModel):
    amount: float = Field(..., gt=0.0)


class MapPayload(BaseModel):
    gridRows: int
    gridCols: int
    gridCells: Dict[str, Any]
    roomDefs: List[Any]
    themeMode: Optional[str] = "light"
    inventoryViewMode: Optional[str] = "list"


# ==========================================
# 4. ENDPOINTY AUTORYZACJI
# ==========================================
@app.get("/")
async def root():
    return {"message": "Home Inventory API działa poprawnie!"}


@app.post("/auth/register", status_code=status.HTTP_201_CREATED)
async def register(payload: UserAuthSchema):
    username = payload.username.strip().lower()
    if len(username) < 3 or len(payload.password) < 4:
        raise HTTPException(status_code=400, detail="Nazwa użytkownika min. 3 znaki, hasło min. 4 znaki.")

    existing_user = await db.users.find_one({"username": username})
    if existing_user:
        raise HTTPException(status_code=400, detail="Użytkownik o takiej nazwie już istnieje.")

    user_doc = {
        "username": username,
        "password_hash": hash_password(payload.password),
        "created_at": datetime.utcnow().isoformat()
    }
    await db.users.insert_one(user_doc)
    token = create_access_token(data={"sub": username})
    return {"token": token, "username": username}


@app.post("/auth/login")
async def login(payload: UserAuthSchema):
    username = payload.username.strip().lower()
    user = await db.users.find_one({"username": username})
    if not user or not verify_password(payload.password, user["password_hash"]):
        raise HTTPException(status_code=400, detail="Nieprawidłowa nazwa użytkownika lub hasło.")

    token = create_access_token(data={"sub": username})
    return {"token": token, "username": username}


# ==========================================
# 5. ENDPOINTY PRODUKTÓW & MAPY (ZABEZPIECZONE)
# ==========================================
@app.get("/barcode/{ean}")
async def fetch_product_by_barcode(ean: str):
    url = f"https://world.openfoodfacts.org/api/v2/product/{ean}.json"
    headers = {"User-Agent": "HomeInventoryApp/1.0 (contact@example.com)"}

    async with httpx.AsyncClient() as http_client:
        response = await http_client.get(url, headers=headers)

    if response.status_code != 200:
        raise HTTPException(status_code=404, detail="Błąd bazy EAN")

    data = response.json()
    if data.get("status") != 1:
        raise HTTPException(status_code=404, detail="Nie znaleziono produktu")

    product = data.get("product", {})
    return {
        "barcode": ean,
        "name": product.get("product_name_pl") or product.get("product_name") or "Nieznany produkt",
        "brand": product.get("brands", ""),
        "quantity_string": product.get("quantity", ""),
        "image_url": product.get("image_url", ""),
        "category": product.get("categories_tags", ["żywność"])[0] if product.get("categories_tags") else "żywność"
    }


@app.get("/items")
async def get_items(
        location: Optional[str] = Query(None),
        category: Optional[str] = Query(None),
        username: str = Depends(get_current_user)
):
    query = {"owner": username}
    if location:
        query["location"] = location
    if category:
        query["category"] = category

    items = []
    cursor = db.items.find(query).sort("created_at", -1)
    async for doc in cursor:
        doc["id"] = str(doc["_id"])
        del doc["_id"]
        items.append(doc)
    return items


@app.post("/items", status_code=status.HTTP_201_CREATED)
async def add_item(item: ItemSchema, username: str = Depends(get_current_user)):
    doc = item.model_dump()
    doc["owner"] = username
    doc["created_at"] = datetime.utcnow().isoformat()
    result = await db.items.insert_one(doc)
    doc["id"] = str(result.inserted_id)
    del doc["_id"]
    return {"message": "Dodano pomyślnie", "item": doc}


@app.patch("/items/{name}/deduct")
async def deduct_item(name: str, payload: DeductSchema, username: str = Depends(get_current_user)):
    item = await db.items.find_one({"name": name, "owner": username})
    if not item:
        raise HTTPException(status_code=404, detail="Nie znaleziono przedmiotu")

    new_quantity = max(0.0, item["quantity"] - payload.amount)
    new_status = "zużyte" if new_quantity == 0 else item.get("status", "w_magazynie")

    await db.items.update_one(
        {"name": name, "owner": username},
        {"$set": {"quantity": new_quantity, "status": new_status}}
    )
    return {"message": f"Zaktualizowano {name}", "remaining_quantity": new_quantity, "unit": item.get("unit", "szt")}


@app.put("/items/{item_id}")
async def update_item(item_id: str, item: ItemSchema, username: str = Depends(get_current_user)):
    from bson import ObjectId
    try:
        obj_id = ObjectId(item_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Nieprawidłowe ID")

    update_data = item.model_dump()
    update_data["owner"] = username
    result = await db.items.update_one({"_id": obj_id, "owner": username}, {"$set": update_data})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Nie znaleziono przedmiotu")
    return {"message": "Zaktualizowano pomyślnie", "item": update_data}


@app.delete("/items/{item_id}")
async def delete_item(item_id: str, username: str = Depends(get_current_user)):
    from bson import ObjectId
    try:
        obj_id = ObjectId(item_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Nieprawidłowe ID")

    result = await db.items.delete_one({"_id": obj_id, "owner": username})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Nie znaleziono przedmiotu")
    return {"message": "Przedmiot usunięty"}


@app.get("/map-config")
async def get_map_config(username: str = Depends(get_current_user)):
    config = await db.map_config.find_one({"_id": f"layout_{username}"})
    if not config:
        return {"error": "Not found"}
    config["id"] = str(config["_id"])
    return config


@app.post("/map-config")
async def save_map_config(payload: MapPayload, username: str = Depends(get_current_user)):
    data = payload.dict()
    data["_id"] = f"layout_{username}"
    data["owner"] = username
    await db.map_config.update_one(
        {"_id": f"layout_{username}"},
        {"$set": data},
        upsert=True
    )
    return {"status": "saved"}


# ==========================================
# 6. START SERWERA
# ==========================================
if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)