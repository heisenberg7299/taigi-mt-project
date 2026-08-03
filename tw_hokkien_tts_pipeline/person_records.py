"""
結構化病患/人員姓名記錄，取代「人名靠LLM在遮罩佔位符裡保留」這個不可靠的
做法。

背景：實測發現不管遮罩格式怎麼調整(只遮名字/遮完整姓名)，LLM都會把人名
佔位符整個丟掉——這不是遮罩格式的問題，是生成式翻譯本質上不保證任何
token都會被保留。真正可靠的做法是「稱呼病患」時把姓名整個從送進LLM的
文字裡拿掉，翻譯完再確定性地把「姓名+稱謂」接回去，姓名完全不經過LLM
的生成過程，才能保證100%正確；「描述第三人」時則要求人名/位置/角色關係
一起確認，任何一項確認不了就fail closed，不能只驗證「有沒有出現這個詞」
就算數。

已知病患/人員姓名應該從病患資料庫/結構化輸入取得(不是靠文字裡搜尋姓名
片段這種脆弱的做法)，這裡的 PersonRecord 就是那個結構化輸入的形狀。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class PersonRecord:
    full_name: str
    title: str | None = None  # 先生/小姐/太太/阿嬤/阿公/醫師...
    aliases: list[str] = field(default_factory=list)  # 文字裡可能出現的其他稱呼方式
    role: str = "patient"  # patient / staff / family


# 呼格判斷：句首是「姓名+稱謂」後面接逗號，例如「王小明先生，你的...」，
# 這種結構在中文裡代表直接稱呼對方(第二人稱)，不是在描述第三人
_VOCATIVE_RE = re.compile(r"^([^，,。！?？]{1,10})[，,]")


def is_vocative_address(zh_text: str, person: PersonRecord) -> bool:
    """判斷句首是不是「已知病患姓名+稱謂,」這種呼格用法(直接稱呼病患)。

    用來決定要不要把這句話標成 structured_renderer.StructuredIntent(
    intent="addressing_patient", ...)——實際的「姓名不經過LLM、翻譯完
    確定性接回句首」渲染邏輯在 structured_renderer.py，這裡只負責判斷。
    """
    candidate = person.full_name + (person.title or "")
    m = _VOCATIVE_RE.match(zh_text)
    if not m:
        return False
    head = m.group(1)
    return head == candidate or head == person.full_name


def vocative_remainder(zh_text: str, person: PersonRecord) -> str:
    """回傳句首呼格之後剩下要翻譯的中文片段。呼叫前應先用
    is_vocative_address 確認格式正確。"""
    m = _VOCATIVE_RE.match(zh_text)
    assert m, f"{zh_text!r} 不符合呼格格式, 呼叫前應先用 is_vocative_address 確認"
    return zh_text[m.end():].strip()
