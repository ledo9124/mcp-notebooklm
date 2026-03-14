"""Local language configuration helpers for retained generate commands."""

import json
import logging

from ..paths import get_config_path, get_home_dir

logger = logging.getLogger(__name__)

# Language codes with native names
# Based on BCP 47 / IETF language tags from WIZ_global_data
SUPPORTED_LANGUAGES: dict[str, str] = {
    # Major languages (sorted by usage)
    "en": "English",
    "zh_Hans": "中文（简体）",
    "zh_Hant": "中文（繁體）",
    "es": "Español",
    "es_419": "Español (Latinoamérica)",
    "es_MX": "Español (México)",
    "hi": "हिन्दी",
    "ar_001": "العربية",
    "ar_eg": "العربية (مصر)",
    "pt_BR": "Português (Brasil)",
    "pt_PT": "Português (Portugal)",
    "bn": "বাংলা",
    "ru": "Русский",
    "ja": "日本語",
    "pa": "ਪੰਜਾਬੀ",
    "de": "Deutsch",
    "jv": "Basa Jawa",
    "ko": "한국어",
    "fr": "Français",
    "fr_CA": "Français (Canada)",
    "te": "తెలుగు",
    "vi": "Tiếng Việt",
    "mr": "मराठी",
    "ta": "தமிழ்",
    "tr": "Türkçe",
    "ur": "اردو",
    "it": "Italiano",
    "th": "ไทย",
    "gu": "ગુજરાતી",
    "fa": "فارسی",
    "pl": "Polski",
    "uk": "Українська",
    "ml": "മലയാളം",
    "kn": "ಕನ್ನಡ",
    "or": "ଓଡ଼ିଆ",
    "my": "မြန်မာဘာသာ",
    "sw": "Kiswahili",
    "nl_NL": "Nederlands",
    "ro": "Română",
    "hu": "Magyar",
    "el": "Ελληνικά",
    "cs": "Čeština",
    "sv": "Svenska",
    "be": "Беларуская",
    "bg": "Български",
    "hr": "Hrvatski",
    "sk": "Slovenčina",
    "da": "Dansk",
    "fi": "Suomi",
    "nb_NO": "Norsk Bokmål",
    "nn_NO": "Norsk Nynorsk",
    "he": "עברית",
    "iw": "עברית",  # Legacy code
    "id": "Bahasa Indonesia",
    "ms": "Bahasa Melayu",
    "fil": "Filipino",
    "ceb": "Cebuano",
    "sr": "Српски",
    "sl": "Slovenščina",
    "sq": "Shqip",
    "mk": "Македонски",
    "lt": "Lietuvių",
    "lv": "Latviešu",
    "et": "Eesti",
    "hy": "Հայերեն",
    "ka": "ქართული",
    "az": "Azərbaycanca",
    "af": "Afrikaans",
    "am": "አማርኛ",
    "eu": "Euskara",
    "ca": "Català",
    "gl": "Galego",
    "is": "Íslenska",
    "la": "Latina",
    "ne": "नेपाली",
    "ps": "پښتو",
    "sd": "سنڌي",
    "si": "සිංහල",
    "ht": "Kreyòl Ayisyen",
    "kok": "कोंकणी",
    "mai": "मैथिली",
}


def get_config() -> dict:
    """Read config from config.json."""
    config_path = get_config_path()
    if config_path.exists():
        try:
            return json.loads(config_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            logger.warning("Config file corrupted, using defaults: %s", e)
            return {}
        except OSError as e:
            logger.warning("Could not read config file: %s", e)
            return {}
    return {}


def save_config(config: dict) -> None:
    """Save config to config.json."""
    config_path = get_config_path()
    get_home_dir(create=True)  # Ensure directory exists
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")


def get_language() -> str | None:
    """Get the configured language, or None if not set."""
    return get_config().get("language")


def set_language(code: str) -> None:
    """Set the language in config."""
    config = get_config()
    config["language"] = code
    save_config(config)

__all__ = [
    "SUPPORTED_LANGUAGES",
    "get_config",
    "save_config",
    "get_language",
    "set_language",
]
