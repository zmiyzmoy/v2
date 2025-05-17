import json
import os
from loguru import logger
from typing import Optional, Dict, Any

class I18nLoader:
    def __init__(self, locales_path: str, default_lang: str):
        self.locales_path = locales_path
        self.default_lang = default_lang
        self.translations: Dict[str, Dict[str, str]] = {}
        self._load_translations()

        if not self.translations:
            logger.warning(f"No translation files loaded from the specified path: {self.locales_path}. Using default texts or keys.")
        elif default_lang not in self.translations:
            logger.warning(f"Default language '{default_lang}' not found among loaded translations. Available: {list(self.translations.keys())}. Check path: {self.locales_path}")

    def _load_translations(self):
        if not os.path.isdir(self.locales_path):
            logger.error(f"Locales directory not found: '{self.locales_path}'. Cannot load translations.")
            return
        
        for lang_file in os.listdir(self.locales_path):
            if lang_file.endswith(".json"):
                lang_code = lang_file[:-5]
                file_path = os.path.join(self.locales_path, lang_file)
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        self.translations[lang_code] = json.load(f)
                    logger.debug(f"Successfully loaded translations for language '{lang_code}' from '{file_path}'.")
                except json.JSONDecodeError as e_json:
                    logger.error(f"Failed to decode JSON for language '{lang_code}' from '{file_path}': {e_json}")
                except Exception as e:
                    logger.error(f"Failed to load translations for language '{lang_code}' from '{file_path}': {e}", exc_info=True)

    def get(self, key: str, lang: Optional[str] = None, default_text: Optional[str] = None, **kwargs: Any) -> str:
        effective_lang = lang or self.default_lang
        
        # Попытка получить перевод для запрошенного языка
        translation = self.translations.get(effective_lang, {}).get(key)
        
        # Если не найдено и язык был не дефолтный, пробуем дефолтный язык
        if not translation and effective_lang != self.default_lang:
            translation = self.translations.get(self.default_lang, {}).get(key)
            if translation:
                logger.trace(f"Translation key '{key}' not found for lang '{effective_lang}', using default lang '{self.default_lang}'.")

        # Если перевод все еще не найден, используем default_text или сам ключ
        if not translation:
            if default_text is not None:
                final_text = default_text
                # logger.trace(f"Translation key '{key}' not found for lang '{effective_lang}' or default lang '{self.default_lang}'. Using provided default_text.")
            else:
                final_text = key # Возвращаем сам ключ, если нет ни перевода, ни default_text
                logger.warning(f"Translation key '{key}' not found for lang '{effective_lang}' or default lang '{self.default_lang}'. Returning key itself.")
        else:
            final_text = translation
            
        # Форматирование строки, если переданы kwargs
        try:
            return final_text.format(**kwargs) if kwargs else final_text
        except KeyError as e_format: # Если в строке есть плейсхолдер, а в kwargs нет такого ключа
            logger.error(f"Formatting error for key '{key}' in lang '{effective_lang}'. Missing placeholder: {e_format}. Original text: '{final_text}'")
            return final_text # Возвращаем неформатированный текст в случае ошибки
