"""
jumia_scraper.py
-----------------
Module de scraping pour le projet EcoSort-Search (Jalon 2).

Interroge le moteur de recherche de Jumia Côte d'Ivoire à partir d'un mot-clé
saisi par l'utilisateur et retourne une liste de produits pertinents
(titre, prix, image, lien) prêts à être affichés dans l'interface
(Streamlit / Flask) puis transmis au modèle de Deep Learning.

Utilisation :
    from jumia_scraper import search_jumia
    resultats = search_jumia("bouteille plastique", limit=5)
"""

import time
import random
import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.jumia.ci"
SEARCH_URL = f"{BASE_URL}/catalog/"

# Jumia bloque ou renvoie des pages vides si le User-Agent ressemble à un bot.
# On utilise donc un User-Agent de navigateur classique.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9",
}


def _clean_price(texte_prix: str) -> str:
    """Nettoie le texte brut d'un prix Jumia (ex: '77,950 FCFA13%' -> '77,950 FCFA')."""
    if not texte_prix:
        return None
    # On coupe avant un éventuel pourcentage de réduction accolé au texte
    texte_prix = texte_prix.split("%")[0]
    if "FCFA" in texte_prix:
        texte_prix = texte_prix.split("FCFA")[0].strip() + " FCFA"
    return texte_prix.strip()


def _extract_image_url(article) -> str:
    """
    Jumia charge les images en lazy-loading : l'URL réelle est souvent dans
    data-src plutôt que dans src (qui contient un placeholder gris).
    On essaie plusieurs attributs par sécurité.
    """
    img = article.find("img")
    if img is None:
        return None
    for attr in ("data-src", "data-original", "src"):
        value = img.get(attr)
        if value and not value.startswith("data:image"):
            return value
    return None


def search_jumia(query: str, limit: int = 5, timeout: int = 10) -> list[dict]:
    """
    Recherche un produit sur Jumia CI et retourne une liste de résultats.

    Args:
        query: mot-clé saisi par l'utilisateur (ex: "bouteille plastique")
        limit: nombre maximum de résultats à retourner (3 à 5 recommandé)
        timeout: délai maximum d'attente de la requête HTTP (secondes)

    Returns:
        Liste de dictionnaires : [{"title": ..., "price": ..., "image_url": ...,
                                    "product_url": ...}, ...]
    """
    params = {"q": query}

    try:
        response = requests.get(
            SEARCH_URL, params=params, headers=HEADERS, timeout=timeout
        )
        response.raise_for_status()
    except requests.RequestException as e:
        print(f"[jumia_scraper] Erreur réseau lors de la recherche : {e}")
        return []

    soup = BeautifulSoup(response.text, "html.parser")

    # Jumia utilise généralement <article class="prd ..."> pour chaque produit.
    # On reste tolérant : on cherche toute balise "article" dont la classe
    # contient "prd", pour survivre aux petites variations de markup.
    articles = soup.find_all(
        "article",
        class_=lambda c: c and "prd" in c.split(),
    )

    resultats = []
    for article in articles[:limit]:
        # Le titre est souvent porté par l'attribut "data-name" du lien,
        # ou à défaut par le texte du lien principal.
        link_tag = article.find("a", class_=lambda c: c and "core" in c.split())
        if link_tag is None:
            link_tag = article.find("a")
        if link_tag is None:
            continue

        title = link_tag.get("data-name") or link_tag.get_text(strip=True)
        product_url = link_tag.get("href", "")
        if product_url and not product_url.startswith("http"):
            product_url = BASE_URL + product_url

        price_tag = article.find(class_=lambda c: c and "prc" in c.split())
        price = _clean_price(price_tag.get_text(strip=True)) if price_tag else None

        image_url = _extract_image_url(article)

        if title:
            resultats.append(
                {
                    "title": title,
                    "price": price,
                    "image_url": image_url,
                    "product_url": product_url,
                }
            )

    return resultats


if __name__ == "__main__":
    # Petit test manuel en ligne de commande
    mot_cle = input("Rechercher un produit sur Jumia CI : ")
    produits = search_jumia(mot_cle, limit=5)

    if not produits:
        print("Aucun résultat trouvé (ou la page a été bloquée par Jumia).")
    else:
        for i, p in enumerate(produits, start=1):
            print(f"\n{i}. {p['title']}")
            print(f"   Prix  : {p['price']}")
            print(f"   Image : {p['image_url']}")
            print(f"   Lien  : {p['product_url']}")

    # Bonne pratique : temporiser entre deux appels successifs pour ne pas
    # surcharger le serveur si vous scrapez plusieurs mots-clés d'affilée.
    time.sleep(random.uniform(1, 2))
