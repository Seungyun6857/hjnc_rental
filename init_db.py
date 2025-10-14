# init_db.py
import sqlite3

DB = "rental.db"

def col_exists(cur, table, col):
    cur.execute(f"PRAGMA table_info({table})")
    return any(r[1] == col for r in cur.fetchall())

with sqlite3.connect(DB) as con:
    c = con.cursor()

    # 1) 테이블 생성
    c.execute("""
    CREATE TABLE IF NOT EXISTS equipment (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        item_name TEXT,
        model_name TEXT,
        serial_no TEXT,
        total_qty INTEGER,
        available_qty INTEGER
        -- category는 아래에서 누락 시 보강(ALTER) 처리
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS rental (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_name TEXT,
        dept TEXT,
        phone TEXT,
        start_date TEXT,
        end_date TEXT,
        signature TEXT,
        equipment_id INTEGER,
        serial_no TEXT,
        qty INTEGER,
        rental_date TEXT,
        return_date TEXT,
        status TEXT
    )
    """)

    # (선택) 게시판이 있다면 함께 생성
    c.execute("""
    CREATE TABLE IF NOT EXISTS board (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        content TEXT,
        created_at TEXT DEFAULT (datetime('now','localtime'))
        -- category는 아래에서 누락 시 보강(ALTER) 처리
    )
    """)

    # 2) 누락 컬럼 보강 (이미 있으면 패스)
    if not col_exists(c, "equipment", "category"):
        c.execute("ALTER TABLE equipment ADD COLUMN category TEXT DEFAULT '기타'")
        print("-> equipment.category 컬럼 추가")

    if not col_exists(c, "board", "category"):
        c.execute("ALTER TABLE board ADD COLUMN category TEXT DEFAULT '일반'")
        print("-> board.category 컬럼 추가")

    # 3) 예시 데이터: 비어있을 때만 삽입(중복 방지)
    c.execute("SELECT COUNT(*) FROM equipment")
    if c.fetchone()[0] == 0:
        equipments = [
            ("무전기", "XiR-E8600", "AZH69RDC9JA2AN", 3, 3, "무전기"),
            ("무전기", "XiR-E8600", "AZH69RDC9JB3BN", 2, 2, "무전기"),
            ("배터리_표준형", "PMNN4440AR", "BATT-001", 4, 4, "소모품"),
            ("배터리_대용량형", "PMNN4511A", "BATT-002", 2, 2, "소모품"),
        ]
        c.executemany("""
            INSERT INTO equipment (item_name, model_name, serial_no, total_qty, available_qty, category)
            VALUES (?, ?, ?, ?, ?, ?)
        """, equipments)
        print("-> equipment 샘플 데이터 삽입")

    con.commit()

print("DB 초기화/보강 완료!")
