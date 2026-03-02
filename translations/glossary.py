"""
문맥별 번역 보정용 용어 사전.
원문(한국어)이 키이고, 언어별로 API 대신 사용할 고정 번역을 지정.
예: "원"(화폐 단위) → 영어 "KRW", 스페인어 "KRW" 등.
"""
# source_ko (strip) -> { target_lang -> value }
# 정착 서비스·정착 플랜 관련은 모두 settlement 계열로 통일 (relocation 사용 안 함)
TRANSLATION_GLOSSARY = {
    # 한국 화폐 단위: 원 → KRW (Circle 등 잘못된 번역 방지)
    "원": {
        "en": "KRW",
        "es": "KRW",
        "zh-hans": "KRW",
        "zh-hant": "KRW",
        "vi": "KRW",
    },
    # 정착 서비스 일관 용어: 이주 정보 / 입국·이주 예정일 → settlement
    "이주 정보": {
        "en": "Settlement info",
        "es": "Información de asentamiento",
        "zh-hans": "安家信息",
        "zh-hant": "安家資訊",
        "vi": "Thông tin định cư",
    },
    "입국/이주 예정일": {
        "en": "Entry/settlement date",
        "es": "Fecha de entrada/asentamiento",
        "zh-hans": "入境/安家日期",
        "zh-hant": "入境/安家日期",
        "vi": "Ngày nhập cảnh/định cư",
    },
}


def get_glossary_translation(source_ko: str, target_lang: str) -> str | None:
    """
    원문이 용어 사전에 있으면 해당 언어의 고정 번역을 반환, 없으면 None.
    """
    if not source_ko or not target_lang:
        return None
    key = (source_ko or "").strip()
    if not key:
        return None
    by_lang = TRANSLATION_GLOSSARY.get(key)
    if not by_lang:
        return None
    return (by_lang.get(target_lang) or "").strip() or None
