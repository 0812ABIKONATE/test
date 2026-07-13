"""
jumia_scraper.py
-----------------
Module de scraping pour le projet EcoSort-Search (Jalon 2).

Interroge le moteur de recherche de Jumia Côte d'Ivoire à partir d'un mot-clé
saisi par l'utilisateur et retourne une liste de produits pertinents
(titre, prix, image, lien), prêts à être affichés dans l'interface
(Streamlit / Flask) puis transmis au modèle de Deep Learning.

Version robuste : gère les erreurs réseau (timeout, connexion, HTTP),
les cas où Jumia ne retourne aucun résultat, les entrées invalides,
et retente automatiquement en cas d'échec temporaire.

Utilisation :
    from jumia_scraper import search_jumia

    resultats = search_jumia("bouteille plastique", limit=5)
    if not resultats:
        print("Aucun produit trouvé, ou service momentanément indisponible.")
"""

import logging
import random
import time

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.jumia.ci"
SEARCH_URL = f"{BASE_URL}/catalog/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9",
}

# Configuration des tentatives en cas d'échec réseau temporaire
MAX_RETRIES = 3
BACKOFF_BASE_SECONDS = 1.5  # 1.5s, puis 3s, puis 6s entre les tentatives

logger = logging.getLogger("jumia_scraper")
if not logger.handlers:
    # Config minimale si le module est utilisé seul, sans logging déjà configuré
    # par l'application principale (Streamlit/Flask configurera le sien).
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


class JumiaScraperError(Exception):
    """Erreur générique du scraper Jumia."""


class JumiaNetworkError(JumiaScraperError):
    """Erreur réseau (timeout, connexion impossible, HTTP 4xx/5xx)."""


class JumiaParsingError(JumiaScraperError):
    """La page a été récupérée mais son contenu n'a pas pu être analysé."""


def _clean_price(texte_prix: str) -> str | None:
    """Nettoie le texte brut d'un prix Jumia (ex: '77,950 FCFA13%' -> '77,950 FCFA')."""
    if not texte_prix:
        return None
    texte_prix = texte_prix.split("%")[0]
    if "FCFA" in texte_prix:
        texte_prix = texte_prix.split("FCFA")[0].strip() + " FCFA"
    return texte_prix.strip() or None


def _extract_image_url(article) -> str | None:
    """Récupère l'URL réelle de l'image (Jumia utilise le lazy-loading)."""
    img = article.find("img")
    if img is None:
        return None
    for attr in ("data-src", "data-original", "src"):
        value = img.get(attr)
        if value and not value.startswith("data:image"):
            return value
    return None


def _validate_query(query: str) -> str:
    """
    Valide et nettoie le mot-clé de recherche avant de l'envoyer à Jumia.
    Lève une ValueError si la requête est vide ou trop courte pour être utile.
    """
    if query is None:
        raise ValueError("Le mot-clé de recherche ne peut pas être vide.")
    query = query.strip()
    if len(query) < 2:
        raise ValueError(
            f"Mot-clé trop court ('{query}') : au moins 2 caractères sont requis."
        )
    return query


def _fetch_search_page(query: str, timeout: int, session: requests.Session) -> str:
    """
    Récupère le HTML de la page de résultats Jumia, avec plusieurs tentatives
    en cas d'échec réseau temporaire (timeout, erreur serveur 5xx).

    Lève JumiaNetworkError si toutes les tentatives échouent.
    """
    params = {"q": query}
    derniere_erreur = None

    for tentative in range(1, MAX_RETRIES + 1):
        try:
            response = session.get(
                SEARCH_URL, params=params, headers=HEADERS, timeout=timeout
            )
            response.raise_for_status()
            return response.text

        except requests.Timeout as e:
            derniere_erreur = e
            logger.warning(
                "Tentative %s/%s : délai dépassé lors de la recherche '%s'.",
                tentative, MAX_RETRIES, query,
            )

        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else None
            # Une erreur 4xx (hors 429) est le plus souvent définitive : inutile de réessayer.
            if status is not None and 400 <= status < 500 and status != 429:
                raise JumiaNetworkError(
                    f"Jumia a refusé la requête (HTTP {status}) pour '{query}'. "
                    "Le site bloque peut-être ce type de requête automatisée."
                ) from e
            derniere_erreur = e
            logger.warning(
                "Tentative %s/%s : erreur HTTP %s pour '%s'.",
                tentative, MAX_RETRIES, status, query,
            )

        except requests.ConnectionError as e:
            derniere_erreur = e
            logger.warning(
                "Tentative %s/%s : connexion impossible à Jumia pour '%s'.",
                tentative, MAX_RETRIES, query,
            )

        # Attente progressive avant de retenter (sauf après la dernière tentative)
        if tentative < MAX_RETRIES:
            attente = BACKOFF_BASE_SECONDS * (2 ** (tentative - 1))
            attente += random.uniform(0, 0.5)  # petit jitter pour éviter les motifs réguliers
            time.sleep(attente)

    raise JumiaNetworkError(
        f"Échec de la recherche '{query}' après {MAX_RETRIES} tentatives : {derniere_erreur}"
    )


def search_jumia(
    query: str,
    limit: int = 5,
    timeout: int = 10,
    raise_on_error: bool = False,
) -> list[dict]:
    """
    Recherche un produit sur Jumia CI et retourne une liste de résultats.

    Args:
        query: mot-clé saisi par l'utilisateur (ex: "bouteille plastique")
        limit: nombre maximum de résultats à retourner (3 à 5 recommandé)
        timeout: délai maximum d'attente par tentative de requête (secondes)
        raise_on_error: si True, laisse remonter les exceptions au lieu de les
            avaler et retourner une liste vide. Utile pour les tests unitaires ;
            en production (interface Streamlit), laisser à False pour ne jamais
            planter l'app sur un souci réseau ponctuel.

    Returns:
        Liste de dictionnaires :
        [{"title": ..., "price": ..., "image_url": ..., "product_url": ...}, ...]
        Retourne une liste vide (jamais None) si aucun résultat ou en cas
        d'erreur non fatale, pour que l'appelant n'ait qu'à tester `if resultats:`.
    """
    try:
        query = _validate_query(query)
    except ValueError as e:
        logger.error("Requête invalide : %s", e)
        if raise_on_error:
            raise
        return []

    session = requests.Session()

    try:
        html = _fetch_search_page(query, timeout=timeout, session=session)
    except JumiaNetworkError as e:
        logger.error(str(e))
        if raise_on_error:
            raise
        return []
    finally:
        session.close()

    try:
        soup = BeautifulSoup(html, "html.parser")
        articles = soup.find_all(
            "article",
            class_=lambda c: c and "prd" in c.split(),
        )
    except Exception as e:  # markup vraiment inattendu / corrompu
        logger.error("Impossible d'analyser la page Jumia pour '%s' : %s", query, e)
        if raise_on_error:
            raise JumiaParsingError(str(e)) from e
        return []

    if not articles:
        # Cas fréquent et normal : aucun produit ne correspond au mot-clé,
        # ou Jumia a changé sa structure de page.
        logger.info("Aucun produit trouvé sur Jumia pour '%s'.", query)
        return []

    resultats = []
    for article in articles[:limit]:
        try:
            link_tag = article.find("a", class_=lambda c: c and "core" in c.split())
            if link_tag is None:
                link_tag = article.find("a")
            if link_tag is None:
                continue

            # Le lien "core" englobe tout le bloc (nom, prix, note, avis).
            # On cible d'abord le nom précisément (balise dédiée), et on ne se
            # rabat sur l'attribut data-name ou le texte brut du lien qu'en dernier
            # recours, pour éviter de récupérer prix/note collés au nom.
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

            resultats.append(
                {
                    "title": title,
                    "price": price,
                    "image_url": image_url,
                    "product_url": product_url,
                }
            )
        except Exception as e:
            # Une carte produit malformée ne doit pas faire échouer toute la recherche :
            # on la saute et on continue avec les suivantes.
            logger.warning("Carte produit ignorée (données incomplètes) : %s", e)
            continue

    if not resultats:
        logger.info(
            "Des balises produit ont été trouvées pour '%s' mais aucune n'a pu être "
            "exploitée (structure Jumia probablement changée).", query,
        )

    return resultats


if __name__ == "__main__":
    mot_cle = input("Rechercher un produit sur Jumia CI : ")
    produits = search_jumia(mot_cle, limit=5)

    if not produits:
        print("\nAucun résultat exploitable (mot-clé sans correspondance, "
              "site indisponible, ou structure de page changée — voir les logs ci-dessus).")
    else:
        for i, p in enumerate(produits, start=1):
            print(f"\n{i}. {p['title']}")
            print(f"   Prix  : {p['price']}")
            print(f"   Image : {p['image_url']}")
            print(f"   Lien  : {p['product_url']}")

    time.sleep(random.uniform(1, 2))
