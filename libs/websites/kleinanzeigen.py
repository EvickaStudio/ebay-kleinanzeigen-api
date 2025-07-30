from typing import Dict, List, Optional, Union, Any
from bs4 import BeautifulSoup


def get_element_content(
    soup: BeautifulSoup, selector: str, default: Any = None
) -> Optional[str]:
    element = soup.select_one(selector)
    return element.get_text(strip=True) if element else default


def get_elements_content(soup: BeautifulSoup, selector: str) -> List[str]:
    elements = soup.select(selector)
    return [element.get_text(strip=True) for element in elements]


def get_image_sources(soup: BeautifulSoup, selector: str) -> List[str]:
    images: List[str] = []
    image_element = soup.select_one(selector)
    if image_element and image_element.has_attr("src"):
        images.append(image_element["src"])
    return images


def parse_price(price_text: Optional[str]) -> Dict[str, Union[str, bool]]:
    if not price_text:
        return {"amount": "0", "currency": "€", "negotiable": False}

    price_text = price_text.strip()
    negotiable: bool = "VB" in price_text

    price_text = price_text.replace("VB", "").strip()

    amount: str = price_text.replace("€", "").replace(".", "").replace(",", ".").strip()

    return {"amount": amount, "currency": "€", "negotiable": negotiable}


def get_seller_details(soup: BeautifulSoup) -> Dict[str, Optional[str]]:
    result = {"name": None, "since": None, "type": "private", "badges": []}
    try:
        _get_seller_details_(soup, result)
    except Exception as e:
        print(f"Error getting seller details: {str(e)}")
    return result


def _get_seller_details_(soup, result):
    result["name"] = get_element_content(soup, ".userprofile-vip")

    if seller_type_element := soup.select_one(".userprofile-vip-details-text"):
        seller_type_text = seller_type_element.get_text(strip=True)
        if "Gewerblicher" in seller_type_text:
            result["type"] = "business"

    since_selector = ".userprofile-vip-details-text:has-text('Aktiv seit')"
    if seller_since := get_element_content(soup, since_selector):
        result["since"] = seller_since.replace("Aktiv seit ", "").strip()

    badges_selector = ".userprofile-vip-badges .userbadge-tag"
    badges = get_elements_content(soup, badges_selector)
    result["badges"] = [badge.strip() for badge in badges if badge and badge.strip()]


def get_details(soup: BeautifulSoup) -> Dict[str, str]:
    details: Dict[str, str] = {}
    try:
        detail_items = soup.select("#viewad-details .addetailslist--detail")
        for item in detail_items:
            label_element = item.find(class_="addetailslist--detail--label")
            value_element = item.find(class_="addetailslist--detail--value")
            if label_element and value_element:
                label = label_element.get_text(strip=True)
                value = value_element.get_text(strip=True)
                details[label] = value
    except Exception as e:
        print(f"Error getting details: {str(e)}")
    return details


def get_features(soup: BeautifulSoup) -> List[str]:
    features: List[str] = []
    try:
        feature_elements = soup.select("#viewad-configuration .checktaglist .checktag")
        for feature in feature_elements:
            if feature_text := feature.get_text(strip=True):
                features.append(feature_text)
    except Exception as e:
        print(f"Error getting features: {str(e)}")
    return features


def get_location(soup: BeautifulSoup) -> Dict[str, str]:
    location_text = get_element_content(soup, "#viewad-locality")
    if not location_text:
        return {"zip": "", "city": "", "state": ""}

    location_parts = location_text.split()
    zip_code = location_parts[0]
    city = " ".join(location_parts[1:])
    # State information is not reliably available in the same way
    return {"zip": zip_code, "city": city, "state": ""}


def get_extra_info(soup: BeautifulSoup) -> Dict[str, Optional[str]]:
    result: Dict[str, Optional[str]] = {"created_at": None, "views": "0"}
    try:
        if date_element := soup.select_one(
            "#viewad-extra-info > div:nth-child(1) > span"
        ):
            result["created_at"] = date_element.get_text(strip=True)

        if views_element := soup.select_one("#viewad-cntr-num"):
            result["views"] = views_element.get_text(strip=True)
    except Exception as e:
        print(f"Error getting extra info: {str(e)}")
    return result
