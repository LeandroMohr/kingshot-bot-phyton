"""Panel languages: server-side messages and helpers to localize the schema.

Translatable schema text is written as L(en, pt) and resolved per request with
localize(); the browser sends its language in the X-Lang header.
"""
from __future__ import annotations

LANGS = ("en", "pt-BR")
DEFAULT_LANG = "en"

MESSAGES = {
    "adb_missing": ("adb not found ('{binary}'). Install the Android platform-tools.",
                    "adb não encontrado ('{binary}'). Instale o Android platform-tools."),
    "content_type": ("Content-Type must be application/json.",
                     "Content-Type precisa ser application/json."),
    "body_too_large": ("Request too large.", "Requisição grande demais."),
    "body_not_object": ("Request body must be a JSON object.",
                        "Corpo da requisição precisa ser um objeto JSON."),
    "route_not_found": ("Route not found.", "Rota não encontrada."),
    "invalid_host": ("Invalid host.", "Host inválido."),
    "invalid_port": ("Invalid port.", "Porta inválida."),
    "invalid_account": ("Invalid account ID.", "ID de conta inválido."),
    "invalid_planning": ("Invalid planning data.", "Planejamento inválido."),
    "planning_shape": ("Planning must have 'snapshot' and 'formations'.",
                       "Planejamento precisa ter 'snapshot' e 'formations'."),
    "prefs_not_object": ("preferences must be an object.", "preferences precisa ser um objeto."),
    "invalid_task_list": ("Invalid task list.", "Lista de tarefas inválida."),
    "unknown_pref": ("Unknown preference: {key}", "Preferência desconhecida: {key}"),
    "must_be_int": ("{label}: must be a whole number.", "{label}: precisa ser um número inteiro."),
    "out_of_range": ("{label}: must be between {min} and {max}.",
                     "{label}: precisa estar entre {min} e {max}."),
    "invalid_choice": ("{label}: invalid option.", "{label}: opção inválida."),
    "must_be_bool": ("{label}: must be ON or OFF.", "{label}: precisa ser ON ou OFF."),
    "no_bot": ("No bot on emulator {port}.", "Nenhum bot no emulador {port}."),
    "bot_already_running": ("A bot is already running on emulator {port}.",
                            "Já existe um bot rodando no emulador {port}."),
    "bot_not_running": ("The bot on emulator {port} is not running.",
                        "O bot do emulador {port} não está rodando."),
}


class UserError(ValueError):
    """An error shown to the panel user, translated when sent."""

    def __init__(self, key: str, **params):
        super().__init__(MESSAGES[key][0].format(**params))
        self.key = key
        self.params = params

    def text(self, lang: str) -> str:
        return MESSAGES[self.key][LANGS.index(lang)].format(**self.params)


def L(en: str, pt: str) -> dict:
    return {"en": en, "pt-BR": pt}


def pick_lang(value: str | None) -> str:
    return value if value in LANGS else DEFAULT_LANG


def localize(obj, lang: str):
    """Copy of obj with every L(...) pair replaced by its text in lang."""
    if isinstance(obj, dict):
        if set(obj) == set(LANGS):
            return obj[lang]
        return {key: localize(value, lang) for key, value in obj.items()}
    if isinstance(obj, list):
        return [localize(item, lang) for item in obj]
    return obj
