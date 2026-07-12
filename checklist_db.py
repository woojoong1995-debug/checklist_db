# checklist_db.py
# 불출 체크리스트 전용 DB 관리 파일
# MWS와 완전히 별개의 DB 파일(checklist.db)을 사용한다

import sqlite3
import os

# DB 파일 경로: 이 파이썬 파일과 같은 폴더에 만들어지도록 고정
# (어느 위치에서 실행해도 항상 같은 DB를 쓰게 하기 위함)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "checklist.db")


def get_conn():
    """DB에 연결하고 연결 객체를 돌려준다.
    row_factory 설정 → 결과를 딕셔너리처럼 컬럼명으로 꺼낼 수 있게 함"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """테이블이 없으면 만든다. 서버 시작할 때 한 번 실행"""
    conn = get_conn()
    cur = conn.cursor()

    # ① 원단 규격 마스터: 품번당 규격 1세트
    cur.execute("""
        CREATE TABLE IF NOT EXISTS fabric_specs (
            item_code  TEXT PRIMARY KEY,   -- 품번 (예: A11W000098)
            gsm        REAL NOT NULL,      -- 평량 (예: 46)
            width      REAL NOT NULL,      -- 폭 (예: 195)
            length     REAL NOT NULL,      -- 길이 (예: 2400)
            updated_at TEXT DEFAULT (datetime('now', 'localtime'))
        )
    """)

    # ② 불출 기록: 매일 쌓이는 체크리스트 항목들
    cur.execute("""
        CREATE TABLE IF NOT EXISTS checklist_items (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,  -- 자동 번호
            work_date  TEXT NOT NULL,   -- 작업 날짜 (예: 2026-07-11)
            tab        TEXT NOT NULL,   -- 구분 (1호기/2호기/주향/부업/진위)
            time       TEXT,            -- 시간 (예: 08:19)
            item_code  TEXT NOT NULL,   -- 품번
            qty_type   TEXT NOT NULL,   -- 유형: ea / roll / m
            qty        REAL NOT NULL,   -- 수량 (개수, 롤수, 미터)
            unit       TEXT,            -- 단위 (ea, plt 등 / 개수일 때만)
            kg         REAL,            -- 계산된 kg (원단일 때만)
            checked    INTEGER DEFAULT 0  -- 체크 여부 (0=미완료, 1=완료)
        )
    """)

    conn.commit()
    conn.close()
    print("DB 초기화 완료: 테이블 준비됨")


# =====================================================
# 원단 규격 (fabric_specs) 관련 함수
# =====================================================

def save_spec(item_code, gsm, width, length):
    """품번의 규격을 저장한다.
    이미 있는 품번이면 새 규격으로 덮어쓴다 (INSERT OR REPLACE)"""
    conn = get_conn()
    conn.execute("""
        INSERT OR REPLACE INTO fabric_specs (item_code, gsm, width, length, updated_at)
        VALUES (?, ?, ?, ?, datetime('now', 'localtime'))
    """, (item_code, gsm, width, length))
    conn.commit()
    conn.close()


def get_spec(item_code):
    """품번의 규격을 찾아서 돌려준다. 없으면 None"""
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM fabric_specs WHERE item_code = ?",
        (item_code,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_all_specs():
    """등록된 모든 원단 규격 목록 (나중에 관리 화면용)"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM fabric_specs ORDER BY item_code"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# =====================================================
# 불출 기록 (checklist_items) 관련 함수
# =====================================================

def add_item(work_date, tab, time, item_code, qty_type, qty, unit=None, kg=None):
    """불출 항목 1건을 추가하고, 생성된 id를 돌려준다"""
    conn = get_conn()
    cur = conn.execute("""
        INSERT INTO checklist_items
            (work_date, tab, time, item_code, qty_type, qty, unit, kg)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (work_date, tab, time, item_code, qty_type, qty, unit, kg))
    conn.commit()
    new_id = cur.lastrowid  # 방금 추가된 항목의 자동 번호
    conn.close()
    return new_id


def get_items(work_date, tab=None):
    """특정 날짜의 불출 목록을 돌려준다.
    tab을 주면 그 탭만, 안 주면 그 날짜 전체"""
    conn = get_conn()
    if tab:
        rows = conn.execute("""
            SELECT * FROM checklist_items
            WHERE work_date = ? AND tab = ?
            ORDER BY id
        """, (work_date, tab)).fetchall()
    else:
        rows = conn.execute("""
            SELECT * FROM checklist_items
            WHERE work_date = ?
            ORDER BY id
        """, (work_date,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def toggle_check(item_id):
    """체크 상태를 반대로 뒤집는다 (0→1, 1→0)"""
    conn = get_conn()
    conn.execute("""
        UPDATE checklist_items
        SET checked = CASE checked WHEN 0 THEN 1 ELSE 0 END
        WHERE id = ?
    """, (item_id,))
    conn.commit()
    conn.close()


def delete_item(item_id):
    """항목 1건 삭제"""
    conn = get_conn()
    conn.execute("DELETE FROM checklist_items WHERE id = ?", (item_id,))
    conn.commit()
    conn.close()


def clear_tab(work_date, tab):
    """특정 날짜 + 탭의 항목을 모두 삭제 (하루 마감 정리용)"""
    conn = get_conn()
    conn.execute(
        "DELETE FROM checklist_items WHERE work_date = ? AND tab = ?",
        (work_date, tab)
    )
    conn.commit()
    conn.close()


# 이 파일을 직접 실행하면 (python3 checklist_db.py) DB를 만든다
if __name__ == "__main__":
    init_db()
