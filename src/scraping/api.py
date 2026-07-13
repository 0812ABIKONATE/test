"""
api.py - API FastAPI avec scraper intégré (tout-en-un)
"""
import logging
import requests
from bs4 import BeautifulSoup
from typing import Optional, List
from fastapi import FastAPI, Query
from pydantic import BaseModel
import uvicorn

# Configuration
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("jumia-api")

# ---------- SCRAPER (intégré) ----------
BASE_URL = "https://www.jumia.ci"
SEARCH_URL = f"{BASE_URL}/catalog/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "fr-FR,fr;q=0.9",
}

def _clean_price(texte_prix: str) -> str | None:
    if not texte_prix:
        return None
    texte_prix = texte_prix.split("%")[0]
    if "FCFA" in texte_prix:
        texte_prix = texte_prix.split("FCFA")[0].strip() + " FCFA"
    return texte_prix.strip() or None

def _extract_image_url(article) -> str | None:
    img = article.find("img")
    if img is None:
        return None
    for attr in ("data-src", "data-original", "src"):
        value = img.get(attr)
        if value and not value.startswith("data:image"):
            return value
    return None

def search_jumia(query: str, limit: int = 5) -> list[dict]:
    """Recherche des produits sur Jumia CI"""
    session = requests.Session()
    try:
        params = {"q": query}
        response = session.get(SEARCH_URL, params=params, headers=HEADERS, timeout=10)
        response.raise_for_status()
        html = response.text
    except Exception as e:
        logger.error(f"Erreur lors de la recherche: {e}")
        return []
    finally:
        session.close()
    
    try:
        soup = BeautifulSoup(html, "html.parser")
        articles = soup.find_all("article", class_=lambda c: c and "prd" in c.split())
    except Exception as e:
        logger.error(f"Erreur d'analyse: {e}")
        return []
    
    resultats = []
    for article in articles[:limit]:
        try:
            link_tag = article.find("a", class_=lambda c: c and "core" in c.split()) or article.find("a")
            if link_tag is None:
                continue
            name_tag = article.find(class_=lambda c: c and "name" in c.split())
            if name_tag is not None:
                title = name_tag.get_text(strip=True)
            else:
                title = link_tag.get("data-name") or link_tag.get_text(strip=True)
            if not title:
                continue
            product_url = link_tag.get("href", "")
            if product_url and not product_url.startswith("http"):
                product_url = BASE_URL + product_url
            price_tag = article.find(class_=lambda c: c and "prc" in c.split())
            price = _clean_price(price_tag.get_text(strip=True)) if price_tag else None
            image_url = _extract_image_url(article)
            resultats.append({
                "title": title,
                "price": price,
                "image_url": image_url,
                "product_url": product_url,
            })
        except Exception as e:
            logger.warning(f"Carte produit ignorée: {e}")
            continue
    
    return resultats

# ---------- API ----------
class ProductResponse(BaseModel):
    title: str
    price: Optional[str] = None
    image_url: Optional[str] = None
    product_url: str

class SearchResponse(BaseModel):
    query: str
    count: int
    products: List[ProductResponse] = []

app = FastAPI(title="EcoSort-Search API", version="1.0.0")

@app.get("/")
async def root():
    return {"status": "OK", "message": "API Jumia Scraper fonctionne!"}

@app.get("/search", response_model=SearchResponse)
async def search(
    q: str = Query(..., min_length=2, description="Mot-clé à rechercher"),
    limit: int = Query(5, ge=1, le=20, description="Nombre de résultats")
):
    logger.info(f"Recherche: q='{q}', limit={limit}")
    produits = search_jumia(q, limit=limit)
    return SearchResponse(
        query=q,
        count=len(produits),
        products=[ProductResponse(**p) for p in produits]
    )

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)