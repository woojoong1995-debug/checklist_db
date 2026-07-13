# bot.py
# 불출 체크리스트 텔레그램 봇 - 3단계: 확인 버튼 + 체크리스트 자동 등록
#
# 실행 전 준비:
#   pip3 install python-telegram-bot requests
#   export TELEGRAM_TOKEN="봇토큰"
#   export GEMINI_API_KEY="Gemini 키"
#   export CHECKLIST_URL="체크리스트 서버 주소"   ← 새로 추가!
#     - 맥북 로컬 테스트: http://127.0.0.1:5001
#     - Railway 배포 후:  https://내앱이름.up.railway.app
#   python3 bot.py
#
# 이번 버전에서 바뀐 것:
#   - 분석 결과에 [✅ 등록] [❌ 취소] 버튼이 달린다
#   - ✅ 누르면 체크리스트 서버의 /api/items 로 전송 → 탭에 자동 등록!
#   - 방 이름에 "1호기"가 들어 있으면 1호기 탭으로 (방 이름 → 탭 자동 매핑)

import os
import json
import time
import base64
from datetime import datetime
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, MessageHandler, CallbackQueryHandler, filters, ContextTypes
)

# ── 환경변수에서 설정 읽기 ──
TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
CHECKLIST_URL = os.environ.get("CHECKLIST_URL", "http://127.0.0.1:5001")

if not TOKEN:
    raise SystemExit("환경변수 TELEGRAM_TOKEN이 없습니다.")
if not GEMINI_KEY:
    raise SystemExit("환경변수 GEMINI_API_KEY가 없습니다.")

GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/"
    "models/gemini-2.5-flash:generateContent?key=" + GEMINI_KEY
)

# 체크리스트의 탭 목록 (index.html의 TABS와 같아야 함)
TABS = ["1호기", "2호기", "주향", "부업", "진위"]
DEFAULT_TAB = "1호기"  # 방 이름으로 탭을 못 정할 때 기본값

# 최근 사진 기억용: { (방ID, 사람ID): (사진file_id, 받은시각) }
recent_photos = {}
PHOTO_MEMORY_SEC = 600

# 분석 결과 대기실: 버튼을 누를 때까지 결과를 보관
# { 결과ID: {"items": [...], "tab": "1호기"} }
pending = {}
pending_counter = 0


# =====================================================
# Gemini에게 지시서 + 요청 문구 분석 시키기
# =====================================================

PROMPT = """너는 창고 자재 불출 담당자를 돕는 도우미다.
첨부된 사진은 '포장 지시서 및 공정기록서'이고, 아래는 요청자가 보낸 요청 문구다.

요청 문구: "{request_text}"

요청 문구에는 자재가 여러 개 들어 있을 수 있다.
(예: "인박스 3780개 단상자 11340개 주세요" → 인박스 1건 + 단상자 1건, 총 2건)

지시서의 '투입 물품 내역' 표에서 요청 문구가 가리키는 자재를 **전부** 찾아라.
자재명은 보통 '분류.상세이름' 형태다 (예: 인박스.뷰티팩토리30매패드공용).
요청 문구의 단어(인박스, 카톤, 단상자, 원단, 필름, 사각캡 등)와 자재명을 대조해서 찾으면 된다.

반드시 아래 JSON 형식으로만 답하라. 설명, 인사말, 마크다운 백틱 금지.
{{
  "items": [
    {{
      "item_code": "자재코드 (예: F21X000192)",
      "item_name": "자재명",
      "category": "원단/인박스/카톤/단상자/필름/벌크/기타 중 하나",
      "qty": 숫자 (요청 문구에서 이 자재에 해당하는 수량),
      "unit": "단위 (plt/개/롤/kg/세트 등)",
      "location": "요청 문구에 납품 장소가 있으면 (예: 2층), 없으면 null"
    }}
  ],
  "not_found": ["요청됐지만 지시서에서 못 찾은 자재 이름들 (없으면 빈 배열)"]
}}

수량과 단위는 요청 문구 기준이다 (예: '1파렛트' → qty 1, unit plt / '3780개' → qty 3780, unit 개).
납품 장소(예: '2층')가 문구에 있으면 모든 자재에 같이 적용하라."""


def ask_gemini(image_bytes, request_text):
    """지시서 사진 + 요청 문구를 Gemini에 보내고 파싱 결과(dict)를 돌려준다"""
    body = {
        "contents": [{
            "parts": [
                {"text": PROMPT.format(request_text=request_text)},
                {
                    "inline_data": {
                        "mime_type": "image/jpeg",
                        "data": base64.b64encode(image_bytes).decode()
                    }
                }
            ]
        }]
    }

    res = requests.post(GEMINI_URL, json=body, timeout=60)
    res.raise_for_status()

    text = res.json()["candidates"][0]["content"]["parts"][0]["text"]
    text = text.replace("```json", "").replace("```", "").strip()
    return json.loads(text)


# =====================================================
# 방 이름 → 체크리스트 탭 매핑
# =====================================================

def tab_from_chat(chat):
    """방 이름에 탭 이름이 들어 있으면 그 탭으로.
    예: 방 이름 '1호기 테스트' → '1호기' 탭"""
    title = chat.title or ""
    for tab in TABS:
        if tab in title:
            return tab
    return DEFAULT_TAB


# =====================================================
# 체크리스트 서버에 등록
# =====================================================

def register_items(items, tab):
    """분석된 자재들을 체크리스트 API(/api/items)에 등록한다.
    성공/실패 결과 문자열을 돌려준다"""
    today = datetime.now().strftime("%Y-%m-%d")
    now_time = datetime.now().strftime("%H:%M")

    ok_count = 0
    errors = []

    for item in items:
        data = {
            "date": today,
            "tab": tab,
            "time": now_time,
            "item_code": item.get("item_code"),
            "qty_type": "ea",              # 텔레그램 요청은 일단 개수형으로 등록
            "qty": item.get("qty"),
            "unit": item.get("unit", "개")
        }
        try:
            res = requests.post(CHECKLIST_URL + "/api/items", json=data, timeout=10)
            if res.status_code == 200 and res.json().get("ok"):
                ok_count += 1
            else:
                errors.append(item.get("item_code") + ": " + res.text[:50])
        except Exception as e:
            errors.append(item.get("item_code") + ": " + str(e)[:50])

    result = f"✅ {tab} 탭에 {ok_count}건 등록 완료!"
    if errors:
        result += "\n⚠️ 실패: " + " / ".join(errors)
    return result


# =====================================================
# 텔레그램 메시지 처리
# =====================================================

async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if msg is None:
        return

    key = (msg.chat.id, msg.from_user.id)

    # ── ① 사진이 온 경우 ──
    if msg.photo:
        recent_photos[key] = (msg.photo[-1].file_id, time.time())
        print(f"[사진 수신] 방:{msg.chat.title or '1:1'} / {msg.from_user.first_name}")

        if msg.caption:
            await process_request(msg, context, msg.photo[-1].file_id, msg.caption)
        return

    # ── ② 텍스트가 온 경우 ──
    if msg.text:
        photo_file_id = None

        if msg.reply_to_message and msg.reply_to_message.photo:
            photo_file_id = msg.reply_to_message.photo[-1].file_id
            print("[답장 감지] 원본 사진과 묶어서 처리")
        elif key in recent_photos:
            file_id, saved_at = recent_photos[key]
            if time.time() - saved_at < PHOTO_MEMORY_SEC:
                photo_file_id = file_id
                print("[최근 사진 연결] 10분 내 사진과 묶어서 처리")

        if photo_file_id:
            await process_request(msg, context, photo_file_id, msg.text)
        else:
            await msg.reply_text("지시서 사진과 함께 요청해 주세요. (사진에 답장으로 요청해도 돼요)")


async def process_request(msg, context, photo_file_id, request_text):
    """사진 + 요청 문구를 Gemini로 분석하고, 확인 버튼과 함께 보여준다"""
    global pending_counter

    await msg.reply_text("🔍 지시서 읽는 중...")

    try:
        file = await context.bot.get_file(photo_file_id)
        image_bytes = bytes(await file.download_as_bytearray())

        result = ask_gemini(image_bytes, request_text)
        print("[Gemini 결과]", result)

        items = result.get("items", [])
        not_found = result.get("not_found", [])

        if not items:
            await msg.reply_text(
                "❓ 지시서에서 요청하신 자재를 찾지 못했어요.\n요청 문구: " + request_text
            )
            return

        # 이 방이 어느 탭인지 결정
        tab = tab_from_chat(msg.chat)

        # ── 결과 메시지 만들기 ──
        circled = "①②③④⑤⑥⑦⑧⑨⑩"
        reply = f"📋 요청 확인 ({len(items)}건) → [{tab}] 탭\n─────────────\n"

        for i, item in enumerate(items):
            num = circled[i] if i < len(circled) else f"{i+1}."
            qty = item.get("qty")
            qty_str = f"{qty:,}" if isinstance(qty, (int, float)) else str(qty)

            reply += f"{num} {item.get('item_code')} · {item.get('category')}\n"
            reply += f"    {item.get('item_name')}\n"
            reply += f"    수량: {qty_str} {item.get('unit')}"
            if item.get("location"):
                reply += f" / 납품: {item['location']}"
            reply += "\n"

        if not_found:
            reply += "─────────────\n❓ 지시서에서 못 찾음: " + ", ".join(not_found) + "\n"

        reply += "─────────────\n등록할까요?"

        # ── 결과를 대기실에 보관하고, 버튼 만들기 ──
        pending_counter += 1
        result_id = str(pending_counter)
        pending[result_id] = {"items": items, "tab": tab}

        buttons = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ 등록", callback_data="ok:" + result_id),
            InlineKeyboardButton("❌ 취소", callback_data="no:" + result_id),
        ]])

        await msg.reply_text(reply, reply_markup=buttons)

    except Exception as e:
        print("[오류]", e)
        await msg.reply_text("⚠️ 처리 중 오류가 났어요: " + str(e))


async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """[✅ 등록] [❌ 취소] 버튼이 눌렸을 때 실행"""
    query = update.callback_query
    await query.answer()  # 버튼 로딩 표시 끄기

    action, result_id = query.data.split(":")
    data = pending.pop(result_id, None)  # 대기실에서 꺼내기 (한 번 쓰면 제거)

    if data is None:
        await query.edit_message_text("⏰ 이 요청은 만료됐어요. 다시 요청해 주세요.")
        return

    if action == "no":
        await query.edit_message_text("❌ 취소했어요.")
        return

    # ✅ 등록: 체크리스트 서버로 전송
    result_text = register_items(data["items"], data["tab"])

    # 원래 메시지 내용은 남기고, 버튼 자리에 결과를 붙임
    original = query.message.text.rsplit("등록할까요?", 1)[0]
    await query.edit_message_text(original + result_text)


def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(MessageHandler(filters.ALL, on_message))
    app.add_handler(CallbackQueryHandler(on_button))  # 버튼 처리 담당
    print("봇 시작! (3단계: 체크리스트 자동 등록)")
    print("체크리스트 서버:", CHECKLIST_URL)
    app.run_polling()


if __name__ == "__main__":
    main()
