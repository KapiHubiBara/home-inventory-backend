# ==========================================
# 1. IMPORTY (Narzędzia, których używamy)
# ==========================================
from datetime import datetime  # Służy do pobierania aktualnej daty i godziny
from typing import Optional, List, Dict, Any  # Pozwala pisać "Optional", czyli że pole może być puste (None)
import os  # Pozwala czytać zmienne systemowe z pliku .env (np. hasło do bazy)
from dotenv import load_dotenv  # Wczytuje nasz plik .env z dysku
from fastapi import FastAPI, HTTPException, status, Query  # Główny silnik naszej aplikacji API
from motor.motor_asyncio import AsyncIOMotorClient  # Biblioteka do szybkiego łączenia się z MongoDB (asynchronicznie)
from pydantic import BaseModel, Field  # Pilnuje typów danych (żeby tekst to był tekst, a liczba to liczba)
import httpx  # Narzędzie do wysyłania zapytań HTTP do innych stron (jak Open Food Facts)

# Ładujemy zmienne z pliku .env (żeby Python widział Twój link do MongoDB Atlas)
load_dotenv()

# Tworzymy aplikację FastAPI – to pod tym obiektem rejestrujemy wszystkie ścieżki
app = FastAPI(title="Home Inventory API")

# ==========================================
# 2. POŁĄCZENIE Z BAZĄ DANYCH (MongoDB Atlas)
# ==========================================
# Wyciągamy z pliku .env link do bazy i nazwę samej bazy
MONGO_URI = os.getenv("MONGO_URI")
DB_NAME = os.getenv("DB_NAME", "home_inventory")

# Tworzymy klienta bazy (czyli nasze aktywne połączenie przez internet)
client = AsyncIOMotorClient(MONGO_URI)
# Wybieramy konkretną bazę danych w MongoDB
db = client[DB_NAME]


# ==========================================
# 3. MODELE DANYCH (Formularze walidacji)
# ==========================================

class ItemSchema(BaseModel):
    name: str = Field(..., examples=["Ibuprofen 400mg"])
    barcode: Optional[str] = Field(None, examples=["5902020163220"])
    brand: Optional[str] = Field(None, examples=["Hasco-Lek"])
    quantity: float = Field(default=1.0, ge=0.0, examples=[20.0])
    unit: str = Field(default="szt", examples=["tabl"])
    location: str = Field(default="Spiżarnia", examples=["Apteczka"])
    category: Optional[str] = Field(default="inne", examples=["Leki"])
    status: Optional[str] = Field(default="w_magazynie", examples=["w_magazynie"])
    expiry_date: Optional[str] = Field(None, examples=["2027-12-31"])
    notes: Optional[str] = Field(None, examples=["Został 1 blister"])


class DeductSchema(BaseModel):
    amount: float = Field(..., gt=0.0, examples=[2.0])


class MapPayload(BaseModel):
    gridRows: int
    gridCols: int
    gridCells: Dict[str, Any]
    roomDefs: List[Any]
    themeMode: Optional[str] = "light"
    inventoryViewMode: Optional[str] = "list"


# ==========================================
# 4. ENDPOINTY (Adresy URL w naszym API)
# ==========================================

@app.get("/")
async def root():
    return {"message": "Home Inventory API działa poprawnie!"}


# --- ENDPOINT 1: Pobieranie danych produktu po kodzie kreskowym ---
@app.get("/barcode/{ean}")
async def fetch_product_by_barcode(ean: str):
    url = f"https://world.openfoodfacts.org/api/v2/product/{ean}.json"
    headers = {"User-Agent": "HomeInventoryApp/1.0 (contact@example.com)"}

    async with httpx.AsyncClient() as http_client:
        response = await http_client.get(url, headers=headers)

    if response.status_code != 200:
        raise HTTPException(status_code=404, detail="Błąd połączenia z bazą EAN")

    data = response.json()
    if data.get("status") != 1:
        raise HTTPException(status_code=404, detail="Nie znaleziono produktu w bazie Open Food Facts")

    product = data.get("product", {})
    return {
        "barcode": ean,
        "name": product.get("product_name_pl") or product.get("product_name") or "Nieznany produkt",
        "brand": product.get("brands", ""),
        "quantity_string": product.get("quantity", ""),
        "image_url": product.get("image_url", ""),
        "category": product.get("categories_tags", ["żywność"])[0] if product.get("categories_tags") else "żywność"
    }


# --- ENDPOINT 2: Pobieranie listy naszych rzeczy ze spiżarni/domu ---
@app.get("/items")
async def get_items(
        location: Optional[str] = Query(None, description="Filtruj po lokalizacji (np. Apteczka, Spiżarnia)"),
        category: Optional[str] = Query(None, description="Filtruj po kategorii")
):
    query = {}
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


# --- ENDPOINT 3: Dodawanie nowego przedmiotu do bazy ---
@app.post("/items", status_code=status.HTTP_201_CREATED)
async def add_item(item: ItemSchema):
    doc = item.model_dump()
    doc["created_at"] = datetime.utcnow().isoformat()
    result = await db.items.insert_one(doc)
    doc["id"] = str(result.inserted_id)
    del doc["_id"]
    return {"message": "Przedmiot został pomyślnie dodany", "item": doc}


# --- ENDPOINT 4: Zużywanie zapasów (odejmowanie ilości) ---
@app.patch("/items/{name}/deduct")
async def deduct_item(name: str, payload: DeductSchema):
    item = await db.items.find_one({"name": name})
    if not item:
        raise HTTPException(status_code=404, detail="Nie znaleziono takiego przedmiotu w bazie")

    new_quantity = max(0.0, item["quantity"] - payload.amount)
    new_status = "zużyte" if new_quantity == 0 else item.get("status", "w_magazynie")

    await db.items.update_one(
        {"name": name},
        {"$set": {"quantity": new_quantity, "status": new_status}}
    )

    return {
        "message": f"Zaktualizowano stan dla {name}",
        "remaining_quantity": new_quantity,
        "unit": item.get("unit", "szt")
    }


# --- ENDPOINT 5: Aktualizacja danych przedmiotu ---
@app.put("/items/{item_id}")
async def update_item(item_id: str, item: ItemSchema):
    from bson import ObjectId
    try:
        obj_id = ObjectId(item_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Nieprawidłowy format ID")

    update_data = item.model_dump()
    result = await db.items.update_one({"_id": obj_id}, {"$set": update_data})

    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Nie znaleziono przedmiotu")

    return {"message": "Zaktualizowano pomyślnie", "item": update_data}


# --- ENDPOINT 6: Usuwanie przedmiotu ---
@app.delete("/items/{item_id}")
async def delete_item(item_id: str):
    from bson import ObjectId
    try:
        obj_id = ObjectId(item_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Nieprawidłowy format ID")

    result = await db.items.delete_one({"_id": obj_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Nie znaleziono przedmiotu")
    return {"message": "Przedmiot usunięty"}


# --- ENDPOINT 7 i 8: Pobieranie i zapisywanie konfiguracji mapy/siatki ---
@app.get("/map-config")
async def get_map_config():
    config = await db.map_config.find_one({"_id": "home_layout"})
    if not config:
        return {"error": "Not found"}
    config["id"] = str(config["_id"])
    return config


@app.post("/map-config")
async def save_map_config(payload: MapPayload):
    data = payload.dict()
    data["_id"] = "home_layout"
    await db.map_config.update_one(
        {"_id": "home_layout"},
        {"$set": data},
        upsert=True
    )
    return {"status": "saved"}


# ==========================================
# 5. START SERWERA
# ==========================================
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)