# app.py
# 불출 체크리스트 Flask 서버
# checklist_db.py의 함수들을 웹 주소(API)로 연결하는 역할

import os
from flask import Flask, request, jsonify, send_file
import checklist_db as db

app = Flask(__name__)

# 서버가 시작될 때 테이블이 없으면 만들어 둔다
db.init_db()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


# =====================================================
# 화면 (index.html) 제공
# =====================================================

@app.route("/")
def index():
    """접속하면 체크리스트 화면을 보여준다"""
    return send_file(os.path.join(BASE_DIR, "index.html"))


# =====================================================
# 원단 규격 API
# =====================================================

@app.route("/api/spec/<item_code>", methods=["GET"])
def api_get_spec(item_code):
    """품번으로 규격 조회
    예: GET /api/spec/A11W000098
    → 프론트에서 품번 입력하면 이 주소를 불러서 규격 자동 채움"""
    spec = db.get_spec(item_code.upper())
    if spec:
        return jsonify({"found": True, "spec": spec})
    # 등록 안 된 품번이면 found: False (에러 아님, 정상 상황)
    return jsonify({"found": False})


@app.route("/api/spec", methods=["POST"])
def api_save_spec():
    """규격 저장 (새 품번 등록 또는 기존 규격 수정)
    보내는 데이터 예: {"item_code": "A11W000098", "gsm": 46, "width": 195, "length": 2400}"""
    data = request.get_json()

    # 필수 값 확인
    for key in ("item_code", "gsm", "width", "length"):
        if not data.get(key):
            return jsonify({"ok": False, "error": key + " 값이 없습니다"}), 400

    db.save_spec(
        data["item_code"].strip().upper(),
        float(data["gsm"]),
        float(data["width"]),
        float(data["length"])
    )
    return jsonify({"ok": True})


@app.route("/api/specs", methods=["GET"])
def api_all_specs():
    """등록된 전체 규격 목록"""
    return jsonify(db.get_all_specs())


# =====================================================
# 불출 기록 API
# =====================================================

@app.route("/api/items", methods=["GET"])
def api_get_items():
    """특정 날짜(+탭)의 불출 목록 조회
    예: GET /api/items?date=2026-07-11&tab=1호기"""
    work_date = request.args.get("date")
    tab = request.args.get("tab")  # 없으면 그 날짜 전체

    if not work_date:
        return jsonify({"ok": False, "error": "date 값이 없습니다"}), 400

    return jsonify(db.get_items(work_date, tab))


@app.route("/api/items", methods=["POST"])
def api_add_item():
    """불출 항목 추가
    보내는 데이터 예:
    개수: {"date": "2026-07-11", "tab": "1호기", "time": "08:19",
           "item_code": "H100000030", "qty_type": "ea", "qty": 26100, "unit": "ea"}
    원단: {"date": "2026-07-11", "tab": "1호기", "time": "11:52",
           "item_code": "A11W000098", "qty_type": "roll", "qty": 40,
           "gsm": 46, "width": 195, "length": 2400}"""
    data = request.get_json()

    # 필수 값 확인
    for key in ("date", "tab", "item_code", "qty_type", "qty"):
        if not data.get(key):
            return jsonify({"ok": False, "error": key + " 값이 없습니다"}), 400

    item_code = data["item_code"].strip().upper()
    qty_type = data["qty_type"]
    qty = float(data["qty"])
    unit = None
    kg = None

    if qty_type == "roll":
        # 원단이면 규격이 꼭 필요하다
        gsm = data.get("gsm")
        width = data.get("width")
        length = data.get("length")
        if not (gsm and width and length):
            return jsonify({"ok": False, "error": "원단 규격(gsm/width/length)이 없습니다"}), 400

        gsm, width, length = float(gsm), float(width), float(length)

        # kg 계산은 서버가 책임진다: 평량 × 폭 × 길이 ÷ 1,000,000 × 롤수
        kg = round(gsm * width * length / 1000000 * qty, 2)

        # 이 품번의 규격을 저장 → 다음부터 자동 조회됨
        db.save_spec(item_code, gsm, width, length)

    elif qty_type == "ea":
        unit = data.get("unit", "ea")

    new_id = db.add_item(
        data["date"], data["tab"], data.get("time"),
        item_code, qty_type, qty, unit, kg
    )
    return jsonify({"ok": True, "id": new_id, "kg": kg})


@app.route("/api/items/<int:item_id>/toggle", methods=["POST"])
def api_toggle(item_id):
    """체크 상태 뒤집기 (완료 ↔ 미완료)"""
    db.toggle_check(item_id)
    return jsonify({"ok": True})


@app.route("/api/items/<int:item_id>", methods=["DELETE"])
def api_delete(item_id):
    """항목 1건 삭제"""
    db.delete_item(item_id)
    return jsonify({"ok": True})


@app.route("/api/clear", methods=["POST"])
def api_clear():
    """특정 날짜 + 탭 전체 비우기
    보내는 데이터 예: {"date": "2026-07-11", "tab": "1호기"}"""
    data = request.get_json()
    if not data.get("date") or not data.get("tab"):
        return jsonify({"ok": False, "error": "date/tab 값이 없습니다"}), 400

    db.clear_tab(data["date"], data["tab"])
    return jsonify({"ok": True})


# =====================================================
# 서버 실행 (개발용)
# =====================================================
if __name__ == "__main__":
    # debug=True: 코드 고치면 서버가 자동 재시작 (개발할 때만 사용)
    app.run(host="0.0.0.0", port=5001, debug=True)
