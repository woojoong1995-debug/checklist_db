# bot.py
# 불출 체크리스트 텔레그램 봇 - 1단계: 메시지 받기 확인
#
# 실행 전 준비:
#   pip3 install python-telegram-bot
#   export TELEGRAM_TOKEN="여기에_토큰"   ← 터미널에서 실행 (코드에 토큰 직접 쓰지 않기!)
#   python3 bot.py

import os
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

# 토큰은 환경변수에서 읽는다 (MWS의 Gemini API 키와 같은 방식)
TOKEN = os.environ.get("TELEGRAM_TOKEN")
if not TOKEN:
    raise SystemExit("환경변수 TELEGRAM_TOKEN이 없습니다. export TELEGRAM_TOKEN=... 먼저 실행하세요.")


async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """방에 메시지가 올라올 때마다 실행되는 함수"""
    msg = update.message
    if msg is None:
        return

    # ── 어떤 정보가 들어오는지 터미널에 출력해 보기 ──
    chat = msg.chat            # 어느 방인지
    user = msg.from_user       # 누가 보냈는지

    print("=" * 40)
    print("방 이름:", chat.title or "(1:1 대화)")
    print("방 ID:", chat.id)          # ← 나중에 방=탭 매핑에 쓸 값!
    print("보낸 사람:", user.first_name)

    if msg.photo:
        print("종류: 사진")
        # msg.caption = 사진에 같이 붙인 글 (있다면)
        if msg.caption:
            print("사진 설명:", msg.caption)
    elif msg.text:
        print("종류: 텍스트")
        print("내용:", msg.text)

    # 답장(Reply)인 경우 → 원본 메시지 정보도 같이 온다
    if msg.reply_to_message:
        origin = msg.reply_to_message
        print("↳ 이 메시지는 답장입니다. 원본:",
              "사진" if origin.photo else (origin.text or "기타"))

    # ── 봇이 대답하기 (받았다는 확인용) ──
    if msg.photo:
        await msg.reply_text("📸 사진 받았어요!")
    elif msg.text:
        await msg.reply_text("💬 받았어요: " + msg.text)


def main():
    # 봇 프로그램 만들기
    app = Application.builder().token(TOKEN).build()

    # "모든 메시지"가 오면 on_message 함수를 실행하도록 연결
    app.add_handler(MessageHandler(filters.ALL, on_message))

    print("봇 시작! 텔레그램에서 봇에게 메시지를 보내보세요. (종료: Ctrl+C)")
    # polling: 봇이 텔레그램 서버에 "새 메시지 있어?"를 계속 물어보는 방식
    # 서버 없이 맥북에서도 동작한다
    app.run_polling()


if __name__ == "__main__":
    main()
