"""Prefecture code map. ISO-3166-2 JP codes."""

import unicodedata

PREFECTURES = {
    "01": ("hokkaido", "Hokkaido", "北海道"),
    "02": ("aomori", "Aomori", "青森県"),
    "03": ("iwate", "Iwate", "岩手県"),
    "04": ("miyagi", "Miyagi", "宮城県"),
    "05": ("akita", "Akita", "秋田県"),
    "06": ("yamagata", "Yamagata", "山形県"),
    "07": ("fukushima", "Fukushima", "福島県"),
    "08": ("ibaraki", "Ibaraki", "茨城県"),
    "09": ("tochigi", "Tochigi", "栃木県"),
    "10": ("gunma", "Gunma", "群馬県"),
    "11": ("saitama", "Saitama", "埼玉県"),
    "12": ("chiba", "Chiba", "千葉県"),
    "13": ("tokyo", "Tokyo", "東京都"),
    "14": ("kanagawa", "Kanagawa", "神奈川県"),
    "15": ("niigata", "Niigata", "新潟県"),
    "16": ("toyama", "Toyama", "富山県"),
    "17": ("ishikawa", "Ishikawa", "石川県"),
    "18": ("fukui", "Fukui", "福井県"),
    "19": ("yamanashi", "Yamanashi", "山梨県"),
    "20": ("nagano", "Nagano", "長野県"),
    "21": ("gifu", "Gifu", "岐阜県"),
    "22": ("shizuoka", "Shizuoka", "静岡県"),
    "23": ("aichi", "Aichi", "愛知県"),
    "24": ("mie", "Mie", "三重県"),
    "25": ("shiga", "Shiga", "滋賀県"),
    "26": ("kyoto", "Kyoto", "京都府"),
    "27": ("osaka", "Osaka", "大阪府"),
    "28": ("hyogo", "Hyogo", "兵庫県"),
    "29": ("nara", "Nara", "奈良県"),
    "30": ("wakayama", "Wakayama", "和歌山県"),
    "31": ("tottori", "Tottori", "鳥取県"),
    "32": ("shimane", "Shimane", "島根県"),
    "33": ("okayama", "Okayama", "岡山県"),
    "34": ("hiroshima", "Hiroshima", "広島県"),
    "35": ("yamaguchi", "Yamaguchi", "山口県"),
    "36": ("tokushima", "Tokushima", "徳島県"),
    "37": ("kagawa", "Kagawa", "香川県"),
    "38": ("ehime", "Ehime", "愛媛県"),
    "39": ("kochi", "Kochi", "高知県"),
    "40": ("fukuoka", "Fukuoka", "福岡県"),
    "41": ("saga", "Saga", "佐賀県"),
    "42": ("nagasaki", "Nagasaki", "長崎県"),
    "43": ("kumamoto", "Kumamoto", "熊本県"),
    "44": ("oita", "Oita", "大分県"),
    "45": ("miyazaki", "Miyazaki", "宮崎県"),
    "46": ("kagoshima", "Kagoshima", "鹿児島県"),
    "47": ("okinawa", "Okinawa", "沖縄県"),
}

_SLUG_TO_CODE = {p[0]: code for code, p in PREFECTURES.items()}
_JP_TO_CODE = {p[2]: code for code, p in PREFECTURES.items()}


def code_to_slug(code: str) -> str | None:
    return PREFECTURES.get(code, (None,))[0]


def code_to_name(code: str) -> str | None:
    return (
        PREFECTURES.get(code, (None, None))[1]
        if len(PREFECTURES.get(code, ())) >= 2
        else None
    )


def slug_to_code(slug: str) -> str | None:
    return _SLUG_TO_CODE.get(slug.lower())


def normalize(text: str) -> tuple[str | None, str | None]:
    """Given any workplace string, return (slug, code) if a prefecture is detected."""
    if not text:
        return None, None
    folded = "".join(
        char
        for char in unicodedata.normalize("NFKD", text).casefold()
        if not unicodedata.combining(char)
    )
    for code, (slug, en, jp) in PREFECTURES.items():
        english = en.casefold()
        japanese_short = jp
        if jp != "北海道":
            japanese_short = jp.removesuffix("都").removesuffix("府").removesuffix("県")
        if (
            jp in text
            or japanese_short in text
            or english in folded
            or slug.replace("-", " ") in folded
        ):
            return slug, code
    return None, None
