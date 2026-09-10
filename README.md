> 🔗 **Frontend Web / Mobile:** [home-inventory-app](https://github.com/KapiHubiBara/home-inventory-app)  
> 🚀 **Działająca aplikacja (Live Demo):** [stashbrain-s53a.vercel.app](https://stashbrain-s53a.vercel.app)
# StashBrain – Backend API

Asynchroniczne REST API wspierające system inwentaryzacji domowej w formie aplikacji o nazwie **StashBrain**. Serwis obsługuje autoryzację wielodostępną, mapowanie pomieszczeń na interaktywnej siatce dwuwymiarowej, śledzenie poziomów zużycia zapasów oraz integrację z bazą kodów kreskowych Open Food Facts. Aplikacja powstała z myślą pomocy ogarnięcia jedynego bajzlu w moim życiu, czyli pokoju :D

Coś gubię, przekładam z miejsca na miejsca podczas wielkich porządków, a po 2 miesiącach dany przedmiot ma status "Zagubiony". Albo skończony jak mąka. Albo przeterminowany jak mleko. Aplikacja ma za zadanie rozwiązać wszystkie moje problemy. W wyszukiwarce wpisuje plastry, a aplikacja pokazuje mi, gdzie te plastry są i nie muszę całego mieszkania przeszukiwać!

---

## Jak to działa

* **Backend (Python & FastAPI):** Cała logika serwera. Wybrałem FastAPI, bo jest szybki, nowoczesny i asynchroniczny – aplikacja działa płynnie i nie zamula przy zapytaniach.
* **Baza danych (MongoDB Atlas & Motor):** Chmurowa baza NoSQL. Ponieważ inwentarz ma strukturę drzewa (Pokój ➔ Mebel ➔ Półka ➔ Pudełko), format JSON pasuje tu idealnie i nie wymagał męczenia się ze sztywnymi relacjami SQL.
* **Logowanie i bezpieczeństwo (JWT + Bcrypt):** Żeby nikt obcy nie grzebał mi w szafach – hasła są bezpiecznie haszowane, sesja działa na tokenach JWT, a w razie sklerozy dodałem awaryjny 4-cyfrowy PIN do resetu hasła, bez zabawy w komplikowanie sprawy z mailami itp.
* **Skaner produktów (Open Food Facts & httpx):** Zamiast ręcznie wklepywać każdy produkt, backend sam odpytuje darmową bazę po kodzie kreskowym EAN i zaciąga nazwę z danymi.
* **Gdzie to stoi (Render):** Żeby aplikacja działała gdzieś dalej niż tylko na moim laptopie (i żebym mógł wygodnie dodawać rzeczy z telefonu stojąc przed szafą), cały backend śmiga w chmurze na platformie Render.
---

## Kluczowe Funkcjonalności

*  **Obsługa siatki 2D i hierarchii:** Zapis układu mieszkania/pokoju oraz pełnej ścieżki położenia przedmiotów.
*  **Masowy import i relokacja:** Endpoint `POST /items/batch` pozwalający hurtowo zasilić bazę danymi z JSON-a (`insert_many`) oraz `POST /items/move-location` do błyskawicznej zmiany lokalizacji całego pudełka lub szafy.
*  **Śledzenie poziomu zużycia:** Obsługa częściowo zużytych opakowań (płyny, chemia, taśmy) za pomocą flagi `tracking:fill` niezależnie od liczby sztuk.
*  **Skaner kodów kreskowych:** Automatyczne pobieranie nazwy, kategorii i miniaturki po kodzie EAN z bazy Open Food Facts.
*  **Bezpieczna sesja:** Ochrona endpointów tokenami Bearer JWT oraz niezależny mechanizm resetu hasła PIN-em.

---

## Uruchomienie Lokalne

### 1. Klonowanie repozytorium
```bash
git clone [https://github.com/KapiHubiBara/home-inventory-backend.git](https://github.com/KapiHubiBara/home-inventory-backend.git)
cd home-inventory-backend
```

### 2. Środowisko wirtualne i zależności
```bash
python -m venv venv
# Windows:
venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate

pip install -r requirements.txt
```

### 3. Połączenie z bazą
Stwórz plik `.env` na wzór `.env.example` i podaj namiary na **swoją** bazę MongoDB (może być darmowy klaster na MongoDB Atlas):
```env
MONGO_URI=twoj_wlasny_link_do_mongodb
DB_NAME=home_inventory
SECRET_KEY=dowolny_losowy_ciag_znakow_do_tokenow
```

### 4. Start serwera deweloperskiego
```bash
uvicorn main:app --reload
```

* API dostępne pod adresem: `http://localhost:8000`
* Interaktywna dokumentacja Swagger UI: `http://localhost:8000/docs`

---

## Główne Endpointy API

| Metoda | Endpoint | Opis działania |
| :--- | :--- | :--- | :---: |
| `POST` | `/auth/register` | Rejestracja użytkownika wraz z kodem PIN |
| `POST` | `/auth/login` | Logowanie i generowanie tokena JWT |
| `POST` | `/auth/reset-password` | Reset hasła użytkownika przy użyciu PIN-u |
| `GET` | `/items` | Pobranie przedmiotów użytkownika z filtrowaniem |
| `POST` | `/items` | Dodanie pojedynczego przedmiotu do inwentarza |
| `POST` | `/items/batch` | Wsadowy import listy przedmiotów z tablicy JSON |
| `POST` | `/items/move-location` | Masowe przepięcie ścieżki lokalizacji |
| `PATCH` | `/items/{name}/deduct` | Zużycie określonej ilości produktu |
| `GET` | `/map-config` | Pobranie konfiguracji siatek pokoi i mebli |
| `POST` | `/map-config` | Zapis aktualnego układu mieszkania |
| `GET` | `/barcode/{ean}` | Proxy do bazy EAN (Open Food Facts) |
