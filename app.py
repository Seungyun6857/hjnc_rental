# app.py
from flask import (
    Flask, render_template, request, redirect, session,
    url_for, jsonify, send_file, current_app, flash, abort
)
import os, io, pytz, json
from io import BytesIO
from datetime import datetime
import pandas as pd

from sqlalchemy import create_engine, text, bindparam
from sqlalchemy.engine import Engine
from dotenv import load_dotenv

# ---------------------------------------------------------------------
# 앱/DB 기본 설정
# ---------------------------------------------------------------------
load_dotenv()  # .env / .env.prod
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "SECRET_KEY_2025")

# 개발 편의: 템플릿 자동 리로드
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.jinja_env.auto_reload = True

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///rental.db")
engine: Engine = create_engine(DATABASE_URL, future=True, pool_pre_ping=True)

def is_sqlite() -> bool:
    return engine.dialect.name == "sqlite"

def is_postgres() -> bool:
    return engine.dialect.name == "postgresql"


# ---------------------------------------------------------------------
# 공통 유틸
# ---------------------------------------------------------------------
def clean_phone(phone: str) -> str:
    return (phone or "").replace("-", "").strip()

def format_phone_kor(phone: str) -> str:
    """국내번호 하이픈 포맷"""
    p = clean_phone(phone)
    if len(p) == 11:
        return f"{p[:3]}-{p[3:7]}-{p[7:]}"
    if len(p) == 10:
        if p.startswith("02"):
            return f"{p[:2]}-{p[2:6]}-{p[6:]}"
        return f"{p[:3]}-{p[3:6]}-{p[6:]}"
    if len(p) == 9 and p.startswith("02"):
        return f"{p[:2]}-{p[2:5]}-{p[5:]}"
    return phone or ""

def now_kst_str() -> str:
    kst = pytz.timezone("Asia/Seoul")
    return datetime.now(kst).strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------------
# 스키마 보장
# ---------------------------------------------------------------------
def ensure_tables():
    """필요한 테이블 및 부족한 컬럼 보장 (SQLite / PostgreSQL 모두 지원)"""
    with engine.begin() as conn:
        # 게시판
        if is_postgres():
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS board (
                    id          INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                    title       TEXT NOT NULL,
                    content     TEXT,
                    created_at  TIMESTAMP DEFAULT NOW(),
                    category    TEXT DEFAULT '공지',
                    is_pinned   INTEGER DEFAULT 0,
                    board_type  TEXT DEFAULT 'general'
                )
            """))
            conn.execute(text("ALTER TABLE board ADD COLUMN IF NOT EXISTS category TEXT DEFAULT '공지'"))
            conn.execute(text("ALTER TABLE board ADD COLUMN IF NOT EXISTS is_pinned INTEGER DEFAULT 0"))
            conn.execute(text("ALTER TABLE board ADD COLUMN IF NOT EXISTS board_type TEXT DEFAULT 'general'"))
        else:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS board (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    content TEXT,
                    created_at TEXT DEFAULT (datetime('now','localtime'))
                )
            """))
            for col_sql in [
                "ALTER TABLE board ADD COLUMN category TEXT DEFAULT '공지'",
                "ALTER TABLE board ADD COLUMN is_pinned INTEGER DEFAULT 0",
                "ALTER TABLE board ADD COLUMN board_type TEXT DEFAULT 'general'",
            ]:
                try: conn.execute(text(col_sql))
                except Exception: pass

        # 일정
        if is_postgres():
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS schedules (
                    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                    title TEXT NOT NULL,
                    start TEXT,
                    end   TEXT,
                    note  TEXT
                )
            """))
        else:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS schedules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    start TEXT,
                    end   TEXT,
                    note  TEXT
                )
            """))

        # 협력업체 주소록(회사)
        if is_postgres():
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS companies (
                    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                    name TEXT NOT NULL,
                    manager TEXT,
                    phone TEXT,
                    group_name TEXT,
                    created_at TIMESTAMP DEFAULT NOW(),
                    memo TEXT
                )
            """))
        else:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS companies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    manager TEXT,
                    phone TEXT,
                    group_name TEXT,
                    created_at TEXT DEFAULT (datetime('now','localtime')),
                    memo TEXT
                )
            """))

        # 사내 주소록(Employees / Departments / Ranks)
        if is_postgres():
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS departments (
                    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE
                )
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS ranks (
                    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE
                )
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS employees (
                    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                    name TEXT NOT NULL,
                    phone TEXT,
                    email TEXT,
                    dept_id INTEGER,
                    rank_id INTEGER,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """))
        else:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS departments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE
                )
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS ranks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE
                )
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS employees (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    phone TEXT,
                    email TEXT,
                    dept_id INTEGER,
                    rank_id INTEGER,
                    created_at TEXT DEFAULT (datetime('now','localtime'))
                )
            """))

        # 장비 재고(묶음)
        if is_postgres():
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS equipment (
                    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                    item_name TEXT NOT NULL,
                    model_name TEXT NOT NULL,
                    category TEXT,
                    location TEXT,
                    total_qty INTEGER DEFAULT 0,
                    available_qty INTEGER DEFAULT 0
                )
            """))
        else:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS equipment (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_name TEXT NOT NULL,
                    model_name TEXT NOT NULL,
                    category TEXT,
                    location TEXT,
                    total_qty INTEGER DEFAULT 0,
                    available_qty INTEGER DEFAULT 0
                )
            """))

        # 개별 장비(단말)
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS walkie_talkie_units (
                unit_no TEXT PRIMARY KEY,
                serial_no TEXT NOT NULL,
                item_name TEXT
            )
        """))
        # bundle_id 보강 (다른 쿼리에서 사용)
        try:
            conn.execute(text("ALTER TABLE walkie_talkie_units ADD COLUMN bundle_id INTEGER"))
        except Exception:
            pass

        # 대여기록
        if is_postgres():
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS rental (
                    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                    user_name TEXT,
                    dept TEXT,
                    phone TEXT,
                    start_date TEXT,
                    end_date TEXT,
                    signature TEXT,
                    serial_no TEXT,
                    qty INTEGER DEFAULT 1,
                    rental_date TEXT,
                    status TEXT DEFAULT 'rented',
                    unit_no TEXT
                )
            """))
        else:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS rental (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_name TEXT,
                    dept TEXT,
                    phone TEXT,
                    start_date TEXT,
                    end_date TEXT,
                    signature TEXT,
                    serial_no TEXT,
                    qty INTEGER DEFAULT 1,
                    rental_date TEXT,
                    status TEXT DEFAULT 'rented',
                    unit_no TEXT
                )
            """))

        # 반납 로그
        if is_postgres():
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS returns_log (
                    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                    rental_id INTEGER NOT NULL,
                    dept TEXT NOT NULL,
                    returner_name TEXT,
                    returner_phone TEXT,
                    returned_at TEXT NOT NULL,
                    FOREIGN KEY (rental_id) REFERENCES rental(id)
                )
            """))
        else:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS returns_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    rental_id INTEGER NOT NULL,
                    dept TEXT NOT NULL,
                    returner_name TEXT,
                    returner_phone TEXT,
                    returned_at TEXT NOT NULL,
                    FOREIGN KEY (rental_id) REFERENCES rental(id)
                )
            """))

        # ⚠️ 전자결재 테이블은 생성하지 않음(삭제)
        # 인덱스
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_rental_dept_status ON rental (dept, status)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_returns_log_rental ON returns_log (rental_id)"))


# ---------------------------------------------------------------------
# 장비 목록/엑셀에서 같이 쓰는 필터
# ---------------------------------------------------------------------
def _build_equipment_filters(req):
    filters = []
    params = {}
    if req.args.get("name"):
        filters.append("item_name LIKE :name")
        params["name"] = f"%{req.args.get('name').strip()}%"
    if req.args.get("model"):
        filters.append("model_name LIKE :model")
        params["model"] = f"%{req.args.get('model').strip()}%"
    if req.args.get("category"):
        filters.append("category = :category")
        params["category"] = req.args.get("category").strip()
    if req.args.get("location"):
        filters.append("location LIKE :location")
        params["location"] = f"%{req.args.get('location').strip()}%"
    if req.args.get("total_qty"):
        filters.append("total_qty = :total_qty")
        params["total_qty"] = req.args.get("total_qty")
    if req.args.get("available_qty"):
        filters.append("available_qty = :available_qty")
        params["available_qty"] = req.args.get("available_qty")
    where_clause = "WHERE " + " AND ".join(filters) if filters else ""
    return where_clause, params


# ---------------------------------------------------------------------
# 사용자 메뉴
# ---------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/user_menu")
def user_menu():
    return render_template("user_menu.html")


# ---------------------------------------------------------------------
# 대여 흐름
# ---------------------------------------------------------------------
@app.route("/rental_info", methods=["GET", "POST"])
def rental_info():
    if request.method == "POST":
        if "agree_terms" not in request.form:
            return "<h3>개인정보 수집 및 이용에 동의해야 다음으로 진행할 수 있습니다.</h3>"

        dept = request.form["dept"]
        user_name = request.form["user_name"]
        phone = clean_phone(request.form["phone"])

        session["rental_info"] = {
            "dept": dept,
            "user_name": user_name,
            "phone": phone,
            "start_date": request.form["start_date"],
            "end_date": request.form["end_date"],
            "signature": request.form["signature"]
        }
        return redirect("/rental_items")
    return render_template("rental_info.html")

@app.route("/rental_items", methods=["GET", "POST"])
def rental_items():
    """
    총 개수(total_count) = 전체 보유 수
    현재 개수(current_count) = 'rented'가 아닌 가용 수
    """
    def _load_inventory():
        with engine.connect() as conn:
            total_count = conn.execute(text("SELECT COUNT(*) FROM walkie_talkie_units")).scalar_one()
            rows = conn.execute(text("""
                SELECT u.unit_no, u.serial_no, u.item_name
                  FROM walkie_talkie_units u
             LEFT JOIN rental r
                    ON TRIM(UPPER(r.unit_no)) = TRIM(UPPER(u.unit_no))
                   AND LOWER(r.status) = 'rented'
                 WHERE r.id IS NULL
              ORDER BY u.unit_no
            """)).all()

        equipments = [{
            "item_name": r[2] or "무전기",
            "model_name": "XiR-E8600",
            "unit_no": r[0],
            "serial_no": r[1],
        } for r in rows]
        current_count = len(equipments)
        return equipments, total_count, current_count

    if request.method == "POST":
        csv = (request.form.get("items") or "").strip()
        selected_units = [x for x in csv.split(",") if x]
        if not selected_units:
            selected_units = (
                request.form.getlist("items") or
                request.form.getlist("equipment_ids") or
                request.form.getlist("equipment_ids[]")
            )

        if not selected_units:
            equipments, total_count, current_count = _load_inventory()
            flash("장비를 한 개 이상 선택해야 대여할 수 있습니다.", "warning")
            return render_template(
                "rental_items.html",
                equipments=equipments,
                total_count=total_count,
                current_count=current_count,
            )

        info = session.get("rental_info")
        if info is None:
            return "<h3>세션이 초기화되었거나 잘못된 접근입니다.</h3>"

        now_kst = now_kst_str()

        with engine.begin() as conn:
            for unit_no in selected_units:
                row = conn.execute(
                    text("SELECT serial_no, COALESCE(item_name,'무전기') FROM walkie_talkie_units WHERE unit_no = :unit_no"),
                    {"unit_no": unit_no},
                ).first()
                serial_no = row[0] if row else f"Unknown-{unit_no}"

                conn.execute(text("""
                    INSERT INTO rental (
                        user_name, dept, phone, start_date, end_date,
                        signature, serial_no, qty, rental_date, status, unit_no
                    ) VALUES (
                        :user_name, :dept, :phone, :start_date, :end_date,
                        :signature, :serial_no, :qty, :rental_date, 'rented', :unit_no
                    )
                """), {
                    "user_name": info["user_name"],
                    "dept": info["dept"],
                    "phone": info["phone"],
                    "start_date": info["start_date"],
                    "end_date": info["end_date"],
                    "signature": info["signature"],
                    "serial_no": serial_no,
                    "qty": 1,
                    "rental_date": now_kst,
                    "unit_no": unit_no,
                })

        # 완료 페이지에서 사용할 정보 저장
        session["last_renter"] = {
            "dept": info["dept"],
            "user_name": info["user_name"],
            "phone": info["phone"],
            "start_date": info["start_date"],
            "end_date": info["end_date"],
        }
        session["last_rental_units"] = selected_units
        session["last_rental_time"] = now_kst

        return redirect("/rental_done")

    # GET
    equipments, total_count, current_count = _load_inventory()
    return render_template(
        "rental_items.html",
        equipments=equipments,
        total_count=total_count,
        current_count=current_count,
    )

@app.route("/rental_done")
def rental_done():
    units = session.get("last_rental_units") or []
    renter = session.get("last_renter") or {}
    if not units or not renter:
        flash("표시할 대여 내역이 없습니다.", "warning")
        return redirect(url_for("user_menu"))

    with engine.connect() as conn:
        rows = conn.execute(
            text("""
                SELECT r.unit_no,
                       r.serial_no,
                       COALESCE(w.item_name, '무전기') AS item_name,
                       COALESCE(r.qty, 1) AS qty
                  FROM rental r
             LEFT JOIN walkie_talkie_units w ON w.unit_no = r.unit_no
                 WHERE r.unit_no IN :units
                   AND LOWER(r.status) = 'rented'
              ORDER BY r.unit_no
            """).bindparams(bindparam("units", expanding=True)),
            {"units": units},
        ).mappings().all()

    items = [{
        "equipment_no": row["unit_no"],
        "equipment_name": row["item_name"],
        "qty": int(row["qty"]),
    } for row in rows]

    total_qty = sum(it["qty"] for it in items) if items else 0

    phone_fmt = format_phone_kor(renter.get("phone", ""))
    start = renter.get("start_date", "")
    end = renter.get("end_date", "")
    period_str = f"{start} ~ {end}" if start or end else ""

    header = {
        "dept": renter.get("dept", ""),
        "username": renter.get("user_name", ""),
        "phone": renter.get("phone", ""),
        "phone_fmt": phone_fmt,
        "start_date": start,
        "end_date": end,
        "period": period_str,
        "created_at": session.get("last_rental_time", ""),
    }

    return render_template(
        "rental_done.html",
        renter=renter,
        items=items,
        total_qty=total_qty,
        header=header,
    )


# ---------------------------------------------------------------------
# 반납 흐름
# ---------------------------------------------------------------------
@app.route("/return_info", methods=["GET", "POST"])
def return_info():
    if request.method == "POST":
        dept = request.form["dept"]
        user_name = request.form["user_name"]
        phone = clean_phone(request.form["phone"])
        if not dept or not user_name or not phone:
            flash("소속/성함/연락처를 모두 입력하세요.", "warning")
            return render_template("return_info.html")
        session["return_info"] = {"dept": dept, "user_name": user_name, "phone": phone}
        return redirect("/return_items")
    return render_template("return_info.html")

@app.route("/return_items", methods=["GET", "POST"])
def return_items():
    info = session.get("return_info")
    if info is None:
        return "<h3>세션이 초기화되었거나 잘못된 접근입니다.</h3>"

    def _load_rented():
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT serial_no, '무전기' AS item_name, 'XiR-E8600' AS model_name, unit_no
                FROM rental
                WHERE dept = :dept AND LOWER(status) = 'rented'
                ORDER BY id DESC
            """), {"dept": info["dept"]}).all()
        total = len(rows)
        current = total
        return rows, total, current

    if request.method == "POST":
        selected_serials = request.form.getlist("items")
        if not selected_serials:
            rented_items, total_count, current_count = _load_rented()
            flash("반납할 장비를 선택하세요.", "warning")
            return render_template(
                "return_items.html",
                rented_items=rented_items,
                total_count=total_count,
                current_count=current_count
            )

        now_str = now_kst_str()
        with engine.begin() as conn:
            for serial_no in selected_serials:
                row = conn.execute(text("""
                    SELECT id FROM rental
                    WHERE dept = :dept AND serial_no = :serial_no AND LOWER(status) = 'rented'
                    ORDER BY id DESC LIMIT 1
                """), {"dept": info["dept"], "serial_no": serial_no}).first()
                if not row:
                    continue
                rental_id = row[0]

                conn.execute(text("""
                    UPDATE rental
                    SET status = 'returned', end_date = :end_date
                    WHERE id = :id AND LOWER(status) = 'rented'
                """), {"end_date": now_str, "id": rental_id})

                conn.execute(text("""
                    INSERT INTO returns_log (rental_id, dept, returner_name, returner_phone, returned_at)
                    VALUES (:rental_id, :dept, :returner_name, :returner_phone, :returned_at)
                """), {
                    "rental_id": rental_id,
                    "dept": info["dept"],
                    "returner_name": info["user_name"],
                    "returner_phone": info["phone"],
                    "returned_at": now_str
                })
        return redirect("/return_done")

    rented_items, total_count, current_count = _load_rented()
    return render_template(
        "return_items.html",
        rented_items=rented_items,
        total_count=total_count,
        current_count=current_count
    )

@app.route("/delete_rentals", methods=["POST"], endpoint="delete_rentals")
def delete_rentals():
    serials = request.form.getlist("serials")
    if serials:
        params = {f"s{i}": v for i, v in enumerate(serials)}
        in_clause = ", ".join(f":s{i}" for i in range(len(serials)))
        with engine.begin() as conn:
            conn.execute(text(f"DELETE FROM rental WHERE serial_no IN ({in_clause}) AND LOWER(status) = 'rented'"), params)
    return redirect(url_for("admin_rent_status"))

@app.route("/return_done")
def return_done():
    return render_template("return_done.html")


# ---------------------------------------------------------------------
# 관리자 로그인/메뉴
# ---------------------------------------------------------------------
@app.route("/admin_login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        if request.form.get("username") == "admin" and request.form.get("password") == "1234":
            session["admin_logged_in"] = True
            session["admin_info"] = {"name": "이승윤", "position": "주임", "dept": "인프라서비스팀"}
            return redirect("/admin_menu")
        return render_template("admin_login.html", error="아이디 또는 비밀번호가 틀렸습니다.")
    return render_template("admin_login.html")

@app.route("/admin_logout")
def admin_logout():
    session.clear()
    return redirect("/")

@app.route("/admin_menu")
def admin_menu():
    if not session.get("admin_logged_in"):
        return redirect("/admin_login")

    with engine.connect() as conn:
        # 최근 공지글 5개
        rows = conn.execute(text("""
            SELECT id, title, category, is_pinned, created_at
            FROM board
            ORDER BY is_pinned DESC, id DESC
            LIMIT 5
        """)).mappings().all()
        posts = [dict(r) for r in rows]

    # 전자결재 제거: 템플릿 호환을 위해 더미 값 제공
    approvals_counts = {"대기": 0, "진행": 0, "반려": 0, "완료": 0}
    approvals_recent = []

    return render_template(
        "admin_menu.html",
        posts=posts,
        show_footer=True,
        approvals_counts=approvals_counts,
        approvals_recent=approvals_recent,
    )


# ---------------------------------------------------------------------
# 장비 재고(관리)
# ---------------------------------------------------------------------
@app.route("/admin_equipment", methods=["GET"])
def admin_equipment():
    if not session.get("admin_logged_in"):
        return redirect("/admin_login")

    where_clause, params = _build_equipment_filters(request)

    try:
        page = max(int(request.args.get("page", 1)), 1)
    except ValueError:
        page = 1
    try:
        per_page = int(request.args.get("per_page", 10))
        if per_page not in (10, 20, 50):
            per_page = 10
    except ValueError:
        per_page = 10
    offset = (page - 1) * per_page

    with engine.connect() as conn:
        rows = conn.execute(text(f"""
            SELECT id, item_name, model_name, category, location, total_qty, available_qty
            FROM equipment
            {where_clause}
            ORDER BY id DESC
            LIMIT :limit OFFSET :offset
        """), {**params, "limit": per_page, "offset": offset}).all()

        total_count = conn.execute(text(f"SELECT COUNT(*) FROM equipment {where_clause}"), params).scalar_one()

        sum_total, sum_available = conn.execute(text(
            f"SELECT COALESCE(SUM(total_qty),0), COALESCE(SUM(available_qty),0) FROM equipment {where_clause}"
        ), params).first()

    total_pages = (total_count + per_page - 1) // per_page
    start_no = (page - 1) * per_page
    equipment_list = [{
        "display_no": start_no + i + 1,
        "id": r[0], "item_name": r[1], "model_name": r[2],
        "category": r[3], "location": r[4],
        "total_qty": r[5], "available_qty": r[6],
    } for i, r in enumerate(rows)]

    categories = ["전자 제품", "소모품", "유지보수 제품", "공구", "기타", "잡자재"]

    return render_template(
        "admin_equipment.html",
        equipment_list=equipment_list,
        categories=categories,
        page=page, total_pages=total_pages, per_page=per_page,
        total_count=total_count,
        total_qty_sum=sum_total, available_qty_sum=sum_available, inuse_qty_sum=max(sum_total - sum_available, 0)
    )

@app.route("/admin/equipment/register", methods=["POST"])
def register_equipment():
    if not session.get("admin_logged_in"):
        return redirect("/admin_login")

    name = (request.form.get("name") or "").strip()
    model = (request.form.get("model") or "").strip()
    category = (request.form.get("category") or "").strip()
    location = (request.form.get("location") or "").strip()

    def _to_int(val, default=0):
        try:
            return int(val)
        except (TypeError, ValueError):
            return default

    total_qty = max(_to_int(request.form.get("total_qty"), 0), 0)
    available_qty = max(_to_int(request.form.get("available_qty"), 0), 0)
    if available_qty > total_qty:
        available_qty = total_qty

    if not name:
        return redirect(url_for("admin_equipment"))

    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO equipment (item_name, model_name, category, location, total_qty, available_qty)
            VALUES (:name, :model, :category, :location, :total, :available)
        """), {"name": name, "model": model, "category": category, "location": location,
               "total": total_qty, "available": available_qty})
    return redirect(url_for("admin_equipment"))

@app.route("/admin/equipment/update_qty", methods=["POST"])
def update_equipment_quantity():
    if not session.get("admin_logged_in"):
        return redirect("/admin_login")

    equip_id = request.form.get("equipment_id")

    def _to_int(val, default=0):
        try:
            return int(val)
        except (TypeError, ValueError):
            return default

    total = max(_to_int(request.form.get("total_qty"), 0), 0)
    available = max(_to_int(request.form.get("available_qty"), 0), 0)
    if available > total:
        available = total

    if not equip_id:
        return redirect(url_for("admin_equipment"))

    with engine.begin() as conn:
        conn.execute(text(
            "UPDATE equipment SET total_qty = :total, available_qty = :available WHERE id = :id"
        ), {"total": total, "available": available, "id": equip_id})
    return redirect(url_for("admin_equipment"))

@app.route("/admin/equipment/delete", methods=["POST"])
def delete_equipments():
    if not session.get("admin_logged_in"):
        return redirect("/admin_login")

    ids = request.form.getlist("equipment_ids")
    id_list = []
    for x in ids or []:
        try:
            id_list.append(int(x))
        except (TypeError, ValueError):
            continue

    if id_list:
        params = {f"id{i}": v for i, v in enumerate(id_list)}
        in_clause = ", ".join(f":id{i}" for i in range(len(id_list)))
        with engine.begin() as conn:
            conn.execute(text(f"DELETE FROM equipment WHERE id IN ({in_clause})"), params)

    return redirect(url_for("admin_equipment"))

@app.route("/admin/equipment/export", methods=["GET"])
def export_equipment():
    if not session.get("admin_logged_in"):
        return redirect("/admin_login")

    where_clause, params = _build_equipment_filters(request)

    with engine.connect() as conn:
        rows = conn.execute(text(f"""
            SELECT id, item_name, model_name, category, location, total_qty, available_qty
            FROM equipment
            {where_clause}
            ORDER BY id DESC
        """), params).all()

    df = pd.DataFrame(rows, columns=["ID", "장비 이름", "모델명", "카테고리", "위치", "총 수량", "사용 가능"])

    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="장비목록")
    buf.seek(0)

    filename = f"equipment_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return send_file(
        buf, as_attachment=True, download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# ---------------------------------------------------------------------
# 대여/반납 상태(관리)
# ---------------------------------------------------------------------
@app.route("/admin_rent_status", methods=["GET"], endpoint="admin_rent_status")
def admin_rent_status():
    if not session.get("admin_logged_in"):
        return redirect("/admin_login")

    q = (request.args.get("q") or "").strip()

    with engine.connect() as conn:
        # 1) 현재 대여중 목록
        base_sql = """
            SELECT id, user_name, dept, phone, serial_no, unit_no,
                   start_date, rental_date, end_date
            FROM rental
            WHERE LOWER(status) = 'rented'
        """
        params = {}
        if q:
            base_sql += " AND (serial_no LIKE :kw OR unit_no LIKE :kw)"
            params["kw"] = f"%{q}%"

        rent_list = conn.execute(text(base_sql + " ORDER BY id DESC"), params).all()
        rental_count = conn.execute(
            text("SELECT COUNT(*) FROM rental WHERE LOWER(status)='rented'")
        ).scalar_one()

        # 2) 개별 단말 중 '가용'(미대여) 목록
        avail_rows = conn.execute(text("""
            SELECT u.unit_no,
                   u.serial_no,
                   COALESCE(u.item_name,'무전기')      AS item_name,
                   COALESCE(u.model_name,'XiR-E8600') AS model_name
              FROM walkie_talkie_units u
              LEFT JOIN rental r
                     ON r.unit_no = u.unit_no
                    AND LOWER(r.status) = 'rented'
             WHERE r.id IS NULL
             ORDER BY u.unit_no
        """)).mappings().all()
        available_units = [dict(r) for r in avail_rows]

        # 3) 요약 박스
        total_units_count = conn.execute(
            text("SELECT COUNT(*) FROM walkie_talkie_units")
        ).scalar_one()

        rented_units = conn.execute(text("""
            SELECT COUNT(DISTINCT unit_no)
              FROM rental
             WHERE LOWER(status)='rented'
        """)).scalar_one()

        available_count = max(total_units_count - (rented_units or 0), 0)

        available_bundles = [{
            "bundle_id": 0,
            "item_name": "무전기",
            "model_name": "XiR-E8600",
            "total_qty": int(total_units_count or 0),
            "available_qty": int(available_count or 0),
        }]

    return render_template(
        "admin_rent_status.html",
        rent_list=rent_list,
        rental_count=rental_count,
        total_units_count=total_units_count,
        available_count=available_count,
        available_units=available_units,
        available_bundles=available_bundles,
        q=q,
    )

@app.route("/admin_return_status", methods=["GET"], endpoint="admin_return_status")
def admin_return_status():
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT r.id, r.user_name, r.dept, r.phone,
                   'S/N : ' || wt.serial_no AS formatted_serial_no,
                   r.unit_no, r.start_date, r.end_date
            FROM rental r
            LEFT JOIN walkie_talkie_units wt ON r.unit_no = wt.unit_no
            WHERE r.status = 'returned'
            ORDER BY r.end_date DESC NULLS LAST
        """)).all()

        return_count = conn.execute(text("SELECT COUNT(*) FROM rental WHERE status = 'returned'")).scalar_one()

    def _fmt_phone(phone):
        phone = (phone or "").replace("-", "")
        if len(phone) == 11: return f"{phone[:3]}-{phone[3:7]}-{phone[7:]}"
        if len(phone) == 10: return f"{phone[:3]}-{phone[3:6]}-{phone[6:]}"
        return phone

    return_list = []
    for row in rows:
        rid, user_name, dept, phone, serial, unit_no, start_date, end_date = row
        return_list.append((rid, user_name, dept, _fmt_phone(phone), serial, unit_no, start_date, end_date))

    return render_template("admin_return_status.html", return_list=return_list, return_count=return_count)

@app.route("/admin/return_status/delete", methods=["POST"], endpoint="delete_returns")
def delete_returns():
    ids = [int(x) for x in request.form.getlist("ids") if str(x).isdigit()]
    if not ids:
        flash("삭제할 항목을 선택하세요.", "warning")
        return redirect(url_for("admin_return_status"))

    stmt = text("DELETE FROM rental WHERE id IN :ids").bindparams(
        bindparam("ids", expanding=True)
    )
    with engine.begin() as conn:
        conn.execute(stmt, {"ids": ids})

    flash(f"{len(ids)}건 삭제 완료", "success")
    return redirect(url_for("admin_return_status"))

# 신규 장비 묶음 + 단말 자동 생성
@app.route("/admin/equipment/add_bundle", methods=["POST"])
def admin_add_equipment_bundle():
    if not session.get("admin_logged_in"):
        return redirect("/admin_login")

    item_name  = (request.form.get("item_name")  or "").strip() or "무전기"
    model_name = (request.form.get("model_name") or "").strip() or "XiR-E8600"
    category   = (request.form.get("category")   or "").strip()
    location   = (request.form.get("location")   or "").strip()

    try:
        total_qty = max(int(request.form.get("total_qty", 0)), 0)
    except ValueError:
        total_qty = 0
    available_qty = total_qty

    try:
        start_unit_no = int((request.form.get("start_unit_no") or "1"))
    except ValueError:
        start_unit_no = 1
    try:
        start_sn = int((request.form.get("start_serial") or "1"))
    except ValueError:
        start_sn = 1

    if total_qty <= 0:
        return redirect(url_for("admin_rent_status"))

    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO equipment (item_name, model_name, category, location, total_qty, available_qty)
            VALUES (:item_name, :model_name, :category, :location, :total_qty, :available_qty)
        """), {
            "item_name": item_name, "model_name": model_name, "category": category,
            "location": location, "total_qty": total_qty, "available_qty": available_qty
        })
        bundle_id = conn.execute(text("SELECT last_insert_rowid()")).scalar_one()

        for i in range(total_qty):
            unit_no   = f"No.{start_unit_no + i}"
            serial_no = f"{start_sn + i:06d}"

            exists = conn.execute(text("""
                SELECT 1 FROM walkie_talkie_units
                WHERE unit_no = :unit_no OR serial_no = :serial_no
                LIMIT 1
            """), {"unit_no": unit_no, "serial_no": serial_no}).first()
            if exists:
                continue

            conn.execute(text("""
                INSERT INTO walkie_talkie_units (unit_no, serial_no, item_name, bundle_id)
                VALUES (:unit_no, :serial_no, :item_name, :bundle_id)
            """), {
                "unit_no": unit_no, "serial_no": serial_no,
                "item_name": item_name, "bundle_id": bundle_id
            })

    return redirect(url_for("admin_rent_status"))

# 가용 장비(미대여) 선택 삭제
@app.route("/admin/walkies/delete", methods=["POST"], endpoint="admin_delete_walkies")
def admin_delete_walkies():
    if not session.get("admin_logged_in"):
        return redirect("/admin_login")

    unit_nos = request.form.getlist("unit_nos")
    if not unit_nos:
        return redirect(url_for("admin_rent_status"))

    with engine.begin() as conn:
        conn.execute(text("""
            DELETE FROM walkie_talkie_units
             WHERE unit_no IN :unit_nos
               AND unit_no NOT IN (SELECT unit_no FROM rental WHERE LOWER(status)='rented')
        """).bindparams(bindparam("unit_nos", expanding=True)), {"unit_nos": unit_nos})

    return redirect(url_for("admin_rent_status"))

@app.route("/admin/walkies/bundle/<int:bundle_id>", methods=["GET"])
def get_bundle_units(bundle_id: int):
    """
    묶음(bundle_id)별 개별 단말 목록 + 대여상태/대여자 정보
    bundle_id == 0 : 미분류(NULL/0)
    """
    where_clause = "u.bundle_id = :bid"
    params = {"bid": bundle_id}
    if bundle_id == 0:
        where_clause = "(u.bundle_id IS NULL OR u.bundle_id = 0)"
        params = {}

    with engine.connect() as conn:
        rows = conn.execute(text(f"""
            SELECT
                u.unit_no,
                u.serial_no,
                COALESCE(u.item_name, '무전기')      AS item_name,
                COALESCE(u.model_name, 'XiR-E8600') AS model_name,
                CASE
                  WHEN EXISTS(
                    SELECT 1 FROM rental r
                     WHERE r.unit_no = u.unit_no
                       AND LOWER(r.status) = 'rented'
                  ) THEN 'rented' ELSE 'available'
                END AS state,
                (
                  SELECT (COALESCE(r.user_name,'') || '/' ||
                          COALESCE(r.dept,'')      || '/' ||
                          COALESCE(r.phone,''))
                    FROM rental r
                   WHERE r.unit_no = u.unit_no
                     AND LOWER(r.status) = 'rented'
                   ORDER BY r.id DESC
                   LIMIT 1
                ) AS borrower,
                (
                  SELECT r.rental_date
                    FROM rental r
                   WHERE r.unit_no = u.unit_no
                     AND LOWER(r.status) = 'rented'
                   ORDER BY r.id DESC
                   LIMIT 1
                ) AS rental_date
            FROM walkie_talkie_units u
            WHERE {where_clause}
            ORDER BY u.unit_no
        """), params).mappings().all()

    return jsonify({"ok": True, "units": [dict(r) for r in rows]})


# ---------------------------------------------------------------------
# 주소록(협력업체/엑셀)
# ---------------------------------------------------------------------
@app.route("/admin/contacts")
def admin_contacts():
    with engine.connect() as conn:
        if is_postgres():
            rows = conn.execute(text("""
                SELECT id, name, manager, phone, group_name,
                       TO_CHAR(created_at,'YYYY-MM-DD HH24:MI:SS') AS created_at,
                       memo
                FROM companies
                ORDER BY id DESC
            """)).all()
        else:
            rows = conn.execute(text("""
                SELECT id, name, manager, phone, group_name,
                       created_at,
                       memo
                FROM companies
                ORDER BY id DESC
            """)).all()

    companies = [{
        "id": r[0], "name": r[1], "manager": r[2], "phone": r[3],
        "group": r[4], "created_at": r[5], "memo": r[6]
    } for r in rows]
    return render_template("admin_contacts.html", companies=companies)

@app.route("/admin/contacts/add", methods=["POST"])
def add_company():
    name = request.form["name"]
    manager = request.form.get("manager", "")
    phone = request.form.get("phone", "")
    group = request.form.get("group", "")
    memo = request.form.get("memo", "")
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO companies (name, manager, phone, group_name, memo)
            VALUES (:name, :manager, :phone, :group, :memo)
        """), {"name": name, "manager": manager, "phone": phone, "group": group, "memo": memo})
    return redirect("/admin/contacts")

@app.route("/admin/contacts/delete/<int:contact_id>")
def delete_contact(contact_id):
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM companies WHERE id = :id"), {"id": contact_id})
    return redirect(url_for("admin_contacts"))

@app.route("/admin/contacts/export_excel")
def export_excel():
    with engine.connect() as conn:
        df = pd.read_sql_query(text("SELECT * FROM companies"), conn)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Companies")
    output.seek(0)
    return send_file(output, download_name="contacts.xlsx", as_attachment=True)

@app.route("/admin/contacts/import_excel", methods=["POST"])
def import_excel():
    file = request.files["file"]
    if file.filename.endswith(".xlsx"):
        df = pd.read_excel(file)
        records = df.to_dict(orient="records")
        with engine.begin() as conn:
            for r in records:
                conn.execute(text("""
                    INSERT INTO companies (name, manager, phone, group_name, memo)
                    VALUES (:name, :manager, :phone, :group_name, :memo)
                """), {
                    "name": r.get("name", ""), "manager": r.get("manager", ""), "phone": r.get("phone", ""),
                    "group_name": r.get("group_name", ""), "memo": r.get("memo", "")
                })
    return redirect("/admin/contacts")


# ---------------------------------------------------------------------
# 게시판
# ---------------------------------------------------------------------
def _read_board_post(post_id: int):
    with engine.connect() as conn:
        if is_postgres():
            row = conn.execute(text("""
                SELECT id, title, content, category, is_pinned, board_type,
                       TO_CHAR(created_at,'YYYY-MM-DD HH24:MI:SS') AS created_at
                FROM board WHERE id = :id
            """), {"id": post_id}).first()
        else:
            row = conn.execute(text("""
                SELECT id, title, content, category, is_pinned, board_type, created_at
                FROM board WHERE id = :id
            """), {"id": post_id}).first()
    if not row:
        return None
    return {
        "id": row[0],
        "title": row[1] or "",
        "content": row[2] or "",
        "category": row[3] or "",
        "is_pinned": int(row[4] or 0),
        "board_type": row[5] or "general",
        "created_at": row[6] or "",
    }

@app.route("/admin/board/api/post/<int:post_id>", methods=["GET"])
def get_board_post_admin_rest(post_id):
    post = _read_board_post(post_id)
    if not post:
        return jsonify({"ok": False, "error": "not_found"}), 200
    return jsonify({"ok": True, "post": post}), 200

@app.route("/board/api/post/<int:post_id>", methods=["GET"])
def get_board_post_rest(post_id):
    post = _read_board_post(post_id)
    if not post:
        return jsonify({"ok": False, "error": "not_found"}), 200
    return jsonify({"ok": True, "post": post}), 200

@app.route("/admin/board/api/post", methods=["GET"])
def get_board_post_admin_query():
    try:
        post_id = int(request.args.get("id", "0"))
    except ValueError:
        post_id = 0
    post = _read_board_post(post_id) if post_id else None
    if not post:
        return jsonify({"ok": False, "error": "not_found"}), 200
    return jsonify({"ok": True, "post": post}), 200

@app.route("/board/api/post", methods=["GET"])
def get_board_post_query():
    try:
        post_id = int(request.args.get("id", "0"))
    except ValueError:
        post_id = 0
    post = _read_board_post(post_id) if post_id else None
    if not post:
        return jsonify({"ok": False, "error": "not_found"}), 200
    return jsonify({"ok": True, "post": post}), 200

@app.route("/admin/board/view/<int:post_id>", methods=["GET"], endpoint="view_board_post")
def view_board_post(post_id):
    with engine.connect() as conn:
        if is_postgres():
            row = conn.execute(text("""
                SELECT id, title, content, category, is_pinned,
                       TO_CHAR(created_at,'YYYY-MM-DD HH24:MI:SS') AS created_at
                FROM board
                WHERE id = :id
            """), {"id": post_id}).first()
        else:
            row = conn.execute(text("""
                SELECT id, title, content, category, is_pinned, created_at
                FROM board
                WHERE id = :id
            """), {"id": post_id}).first()

    if not row:
        return "게시글을 찾을 수 없습니다.", 404

    post = {
        "id": row[0],
        "title": row[1],
        "content": row[2],
        "category": row[3],
        "is_pinned": row[4],
        "created_at": row[5],
    }
    return render_template("board/view.html", post=post)

@app.route("/admin/board/post/<int:post_id>", methods=["GET"], endpoint="admin_board_view")
def admin_board_view_alias(post_id):
    return redirect(url_for("view_board_post", post_id=post_id))

@app.route("/admin/board")
def admin_board():
    return redirect(url_for("admin_board_type", board_type="general"))

@app.route("/admin/board/<board_type>")
def admin_board_type(board_type):
    valid = {"work","general","data","qna","all"}
    if board_type not in valid:
        board_type = "general"

    q = request.args.get("q","").strip()
    category = request.args.get("category","")
    per_page = int(request.args.get("per_page", 10))
    page = max(1, int(request.args.get("page", 1)))
    offset = (page-1)*per_page

    params = {}
    where = "WHERE 1=1"
    if board_type != "all":
        where += " AND board_type = :board_type"
        params["board_type"] = board_type
    if category:
        where += " AND category = :category"
        params["category"] = category
    if q:
        where += " AND (title LIKE :like OR content LIKE :like)"
        params["like"] = f"%{q}%"

    with engine.connect() as conn:
        total = conn.execute(text(f"SELECT COUNT(*) FROM board {where}"), params).scalar_one()

        if is_postgres():
            rows = conn.execute(text(f"""
                SELECT id, title, content, category, is_pinned, board_type,
                       TO_CHAR(created_at,'YYYY-MM-DD HH24:MI:SS') AS created_at
                FROM board
                {where}
                ORDER BY is_pinned DESC, id DESC
                LIMIT :limit OFFSET :offset
            """), {**params, "limit": per_page, "offset": offset}).all()
        else:
            rows = conn.execute(text(f"""
                SELECT id, title, content, category, is_pinned, board_type,
                       created_at
                FROM board
                {where}
                ORDER BY is_pinned DESC, id DESC
                LIMIT :limit OFFSET :offset
            """), {**params, "limit": per_page, "offset": offset}).all()

    posts = [{
        "id": r[0], "title": r[1], "content": r[2],
        "category": r[3], "is_pinned": r[4], "board_type": r[5], "created_at": r[6]
    } for r in rows]

    total_pages = max(1, (total + per_page - 1)//per_page)
    categories = ["", "공지", "안내", "점검", "기타"]  # ""=전체

    tmpl_map = {
        "all": "board/all.html",
        "general": "board/general.html",
        "work": "board/work.html",
        "data": "board/data.html",
        "qna": "board/qna.html",
    }
    tmpl = tmpl_map.get(board_type, "board/general.html")

    return render_template(
        tmpl,
        posts=posts, total=total, page=page, per_page=per_page,
        total_pages=total_pages, q=q, category=category,
        categories=categories, board_type=board_type
    )

@app.post("/admin/board/bulk-delete", endpoint="bulk_delete_board")
def bulk_delete_board():
    ids_raw = request.form.getlist("ids") or request.form.getlist("post_ids")
    ids: list[int] = []
    for x in ids_raw:
        try:
            ids.append(int(x))
        except (TypeError, ValueError):
            continue

    bt = (request.form.get("board_type") or "general").strip() or "general"

    if not ids:
        flash("삭제할 게시글을 선택하세요.", "warning")
        return redirect(url_for("admin_board_type", board_type=bt))

    stmt = text("DELETE FROM board WHERE id IN :ids").bindparams(bindparam("ids", expanding=True))
    with engine.begin() as conn:
        conn.execute(stmt, {"ids": ids})

    flash(f"{len(ids)}건 삭제 완료", "success")
    return redirect(url_for("admin_board_type", board_type=bt))

@app.post("/admin/board/add", endpoint="add_board_post")
def add_board_post():
    title = (request.form.get("title") or "").strip()
    content = (request.form.get("content") or "").strip()
    category = (request.form.get("category") or "").strip()
    is_pinned = 1 if request.form.get("is_pinned") == "1" else 0
    board_type = (request.form.get("board_type") or "general").strip() or "general"

    if not title:
        flash("제목을 입력하세요.", "warning")
        return redirect(url_for("admin_board_type", board_type=board_type))

    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO board (title, content, category, is_pinned, board_type)
            VALUES (:title, :content, :category, :is_pinned, :board_type)
        """), {
            "title": title, "content": content, "category": category,
            "is_pinned": is_pinned, "board_type": board_type
        })

    flash("등록되었습니다.", "success")
    return redirect(url_for("admin_board_type", board_type=board_type))

@app.post("/admin/board/<int:post_id>/toggle-pin", endpoint="toggle_pin")
def toggle_pin(post_id: int):
    bt = (request.args.get("board_type") or "general").strip() or "general"

    with engine.begin() as conn:
        row = conn.execute(text("SELECT is_pinned FROM board WHERE id = :id"), {"id": post_id}).first()
        if not row:
            abort(404)
        new_val = 0 if int(row[0] or 0) else 1
        conn.execute(text("UPDATE board SET is_pinned = :v WHERE id = :id"),
                     {"v": new_val, "id": post_id})

    return redirect(url_for("admin_board_type", board_type=bt))

@app.post("/admin/board/<int:post_id>/delete", endpoint="delete_board_post")
def delete_board_post(post_id: int):
    bt = (request.args.get("board_type") or "general").strip() or "general"
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM board WHERE id = :id"), {"id": post_id})
    flash("삭제되었습니다.", "success")
    return redirect(url_for("admin_board_type", board_type=bt))

@app.get("/admin/board/list", endpoint="board_list")
def board_list_alias():
    bt = (request.args.get("board_type") or "general").strip() or "general"
    return redirect(url_for("admin_board_type", board_type=bt))

@app.get("/board/list")
def board_list_public_alias():
    bt = (request.args.get("board_type") or "general").strip() or "general"
    return redirect(url_for("admin_board_type", board_type=bt))


# ---------------------------------------------------------------------
# 업무 메뉴얼
# ---------------------------------------------------------------------
def _manual_json_path_candidates():
    return [
        os.path.join(current_app.root_path, "manual_data.json"),
        os.path.join(current_app.instance_path, "manual_data.json"),
        os.path.join(current_app.static_folder, "manual", "manual_data.json"),
    ]

def _manual_json_path_for_save():
    for p in _manual_json_path_candidates():
        d = os.path.dirname(p)
        if os.path.isdir(d):
            return p
    fallback_dir = os.path.join(current_app.static_folder, "manual")
    os.makedirs(fallback_dir, exist_ok=True)
    return os.path.join(fallback_dir, "manual_data.json")

def load_manual_data():
    for p in _manual_json_path_candidates():
        if os.path.isfile(p):
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
    return {
        "last_updated": "미설정",
        "sections": [{
            "id": "sample",
            "title": "예시",
            "items": [{
                "id": "sample_item",
                "name": "샘플 항목",
                "images_dir": None,
                "description": "manual_data.json 파일을 준비하면 실제 메뉴얼이 표시됩니다.",
                "actions": [
                    "static/manual/ 아래에 이미지 폴더 생성",
                    "manual_data.json 작성 후 위치 중 한 곳에 배치"
                ],
                "notes": "",
                "contacts": []
            }]
        }]
    }

def save_manual_data(manual: dict):
    manual["last_updated"] = datetime.now().strftime("%Y-%m-%d")
    path = _manual_json_path_for_save()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(manual, f, ensure_ascii=False, indent=2)
    return path

def collect_manual_images(manual: dict):
    base_dir = current_app.static_folder
    allowed_ext = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
    for sec in manual.get("sections", []):
        for item in sec.get("items", []):
            images_dir_raw = item.get("images_dir") or ""
            images_dir = images_dir_raw.strip().lstrip("/\\")
            files = []
            if images_dir:
                abs_dir = os.path.join(base_dir, images_dir.replace("/", os.sep))
                try:
                    if os.path.isdir(abs_dir):
                        for fn in sorted(os.listdir(abs_dir)):
                            ext = os.path.splitext(fn)[1].lower()
                            if ext in allowed_ext:
                                files.append(url_for("static", filename=f"{images_dir}/{fn}"))
                except Exception:
                    pass
            item["images"] = files
    return manual

def _find_section(manual, sec_id):
    for sec in manual.get("sections", []):
        if sec.get("id") == sec_id:
            return sec
    return None

def _find_item(manual, sec_id, item_id):
    sec = _find_section(manual, sec_id)
    if not sec: return None, None
    for it in sec.get("items", []):
        if it.get("id") == item_id:
            return sec, it
    return sec, None

def _gen_id(prefix):
    return f"{prefix}_{int(datetime.now().timestamp()*1000)}"

@app.route("/admin/manual")
def admin_manual():
    manual = load_manual_data()
    manual = collect_manual_images(manual)
    return render_template("admin_manual.html", manual=manual)

@app.route("/admin/manual/section/add", methods=["POST"])
def manual_section_add():
    title = (request.form.get("title") or "").strip()
    if not title:
        return redirect(url_for("admin_manual"))
    manual = load_manual_data()
    manual.setdefault("sections", []).append({"id": _gen_id("sec"), "title": title, "items": []})
    save_manual_data(manual)
    return redirect(url_for("admin_manual"))

@app.route("/admin/manual/section/<sec_id>/update", methods=["POST"])
def manual_section_update(sec_id):
    title = (request.form.get("title") or "").strip()
    manual = load_manual_data()
    sec = _find_section(manual, sec_id)
    if sec and title:
        sec["title"] = title
        save_manual_data(manual)
    return redirect(url_for("admin_manual"))

@app.route("/admin/manual/section/<sec_id>/delete", methods=["POST"])
def manual_section_delete(sec_id):
    manual = load_manual_data()
    manual["sections"] = [s for s in manual.get("sections", []) if s.get("id") != sec_id]
    save_manual_data(manual)
    return redirect(url_for("admin_manual"))

@app.route("/admin/manual/item/add", methods=["POST"])
def manual_item_add():
    sec_id     = request.form.get("sec_id")
    name       = (request.form.get("name") or "").strip()
    images_dir = (request.form.get("images_dir") or "").strip().lstrip("/\\")
    description= (request.form.get("description") or "").strip()
    actions    = [a.strip() for a in (request.form.get("actions") or "").splitlines() if a.strip()]
    contacts   = [c.strip() for c in (request.form.get("contacts") or "").splitlines() if c.strip()]
    notes      = (request.form.get("notes") or "").strip()

    manual = load_manual_data()
    sec = _find_section(manual, sec_id)
    if not sec or not name:
        return redirect(url_for("admin_manual"))

    new = {
        "id": _gen_id("item"),
        "name": name,
        "images_dir": images_dir or None,
        "description": description,
        "actions": actions,
        "contacts": contacts,
        "notes": notes
    }
    sec.setdefault("items", []).append(new)
    save_manual_data(manual)
    return redirect(url_for("admin_manual"))

@app.route("/admin/manual/item/<sec_id>/<item_id>/update", methods=["POST"])
def manual_item_update(sec_id, item_id):
    name       = (request.form.get("name") or "").strip()
    images_dir = (request.form.get("images_dir") or "").strip().lstrip("/\\")
    description= (request.form.get("description") or "").strip()
    actions    = [a.strip() for a in (request.form.get("actions") or "").splitlines() if a.strip()]
    contacts   = [c.strip() for a in (request.form.get("contacts") or "").splitlines() for c in ([a] if a.strip() else [])]
    notes      = (request.form.get("notes") or "").strip()

    manual = load_manual_data()
    sec, it = _find_item(manual, sec_id, item_id)
    if it:
        if name: it["name"] = name
        it["images_dir"] = images_dir or None
        it["description"] = description
        it["actions"] = actions
        it["contacts"] = contacts
        it["notes"] = notes
        save_manual_data(manual)
    return redirect(url_for("admin_manual"))

@app.route("/admin/manual/item/<sec_id>/<item_id>/delete", methods=["POST"])
def manual_item_delete(sec_id, item_id):
    manual = load_manual_data()
    sec = _find_section(manual, sec_id)
    if sec:
        sec["items"] = [x for x in sec.get("items", []) if x.get("id") != item_id]
        save_manual_data(manual)
    return redirect(url_for("admin_manual"))


# ---------------------------------------------------------------------
# 캘린더
# ---------------------------------------------------------------------
@app.route("/calendar")
def calendar():
    return render_template("calendar.html")

@app.route("/get_schedules")
def get_schedules():
    ensure_tables()
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT id, title, start, end, COALESCE(note, '') FROM schedules")).all()
    return jsonify([{"id": r[0], "title": r[1], "start": r[2], "end": r[3], "note": r[4]} for r in rows])

@app.route("/add_schedule", methods=["POST"])
def add_schedule():
    ensure_tables()
    data = request.get_json() or {}
    title = (data.get("title") or "").strip() or "제목 없음"
    start = (data.get("start") or "").strip()
    end   = (data.get("end") or "").strip() or start
    note  = data.get("note", "")
    if not start:
        return jsonify({"status": "error", "message": "start is required"}), 400

    with engine.begin() as conn:
        row = conn.execute(text(
            "INSERT INTO schedules (title, start, end, note) VALUES (:title, :start, :end, :note) RETURNING id"
            if is_postgres() else
            "INSERT INTO schedules (title, start, end, note) VALUES (:title, :start, :end, :note)"
        ), {"title": title, "start": start, "end": end, "note": note})

        if is_postgres():
            sid = row.mappings().first()["id"]
        else:
            sid = conn.execute(text("SELECT last_insert_rowid()")).scalar_one()

    return jsonify({"status": "success", "id": sid})

@app.route("/update_schedule", methods=["POST"])
def update_schedule():
    ensure_tables()
    data = request.get_json() or {}
    sid   = data.get("id")
    title = (data.get("title") or "").strip() or "제목 없음"
    start = (data.get("start") or "").strip()
    end   = (data.get("end") or "").strip() or start
    note  = data.get("note", "")
    if not sid:
        return jsonify({"status": "error", "message": "id required"}), 400
    if not start:
        return jsonify({"status": "error", "message": "start is required"}), 400

    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE schedules SET title=:title, start=:start, end=:end, note=:note WHERE id=:id
        """), {"title": title, "start": start, "end": end, "note": note, "id": sid})
    return jsonify({"status": "success"})

@app.route("/delete_schedule", methods=["POST"])
def delete_schedule():
    ensure_tables()
    data = request.get_json() or {}
    sid = data.get("id")
    if not sid:
        return jsonify({"status": "error", "message": "id required"}), 400
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM schedules WHERE id=:id"), {"id": sid})
    return jsonify({"status": "success"})


# =====================================================================
# 전역 템플릿 변수(회사 정보) & 엔드포인트 존재 여부 확인
# =====================================================================
@app.context_processor
def inject_company_info():
    return {
        "company_name": os.getenv("COMPANY_NAME", "우주정보통신"),
        "company_logo_path": os.getenv("COMPANY_LOGO_PATH", "img/company_logo.svg"),
        "company_addr": os.getenv("COMPANY_ADDR", "경남 창원시 진해구 신항로 433 1층 우주정보통신"),
        "company_tel": os.getenv("COMPANY_TEL", "051-220-2240"),
        "company_ph":  os.getenv("COMPANY_PH",  "010-8703-6857"),
        "company_fax": os.getenv("COMPANY_FAX", "-"),
        "company_notice": os.getenv(
            "COMPANY_NOTICE",
            "※ 본 시스템은 내부 업무용입니다. 무단 접근을 금합니다."
        ),
        "current_year": datetime.now().year,
    }

@app.context_processor
def inject_has_endpoint():
    def has_endpoint(name: str) -> bool:
        return name in current_app.view_functions
    return dict(has_endpoint=has_endpoint)


# ---------------------------------------------------------------------
# 사용자 관리 (사원 리스트 / 사원 추가 / 직급 및 부서 리스트)
# ---------------------------------------------------------------------
@app.route("/admin/users/list", methods=["GET"], endpoint="admin_user_list")
def admin_user_list():
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT e.id, e.name, e.phone, e.email,
                   COALESCE(d.name,'') AS dept_name,
                   COALESCE(r.name,'') AS rank_name,
                   e.created_at
            FROM employees e
            LEFT JOIN departments d ON d.id = e.dept_id
            LEFT JOIN ranks r ON r.id = e.rank_id
            ORDER BY e.id DESC
        """)).mappings().all()
    employees = [dict(r) for r in rows]
    return render_template("users/list.html", employees=employees)

@app.route("/admin/users/new", methods=["GET", "POST"], endpoint="admin_user_add")
def admin_user_add():
    if request.method == "POST":
        name  = (request.form.get("name") or "").strip()
        phone = (request.form.get("phone") or "").strip()
        email = (request.form.get("email") or "").strip()
        dept  = (request.form.get("dept") or "").strip()
        rank  = (request.form.get("rank") or "").strip()

        if not name:
            flash("이름을 입력하세요.", "warning")
            return redirect(url_for("admin_user_add"))

        with engine.begin() as conn:
            # 부서/직급 upsert
            def upsert(table, val):
                if not val: return None
                row = conn.execute(text(f"SELECT id FROM {table} WHERE name=:n"), {"n": val}).first()
                if row: return row[0]
                conn.execute(text(f"INSERT INTO {table}(name) VALUES (:n)"), {"n": val})
                return conn.execute(text("SELECT last_insert_rowid()")).scalar_one()
            dept_id = upsert("departments", dept)
            rank_id = upsert("ranks", rank)

            conn.execute(text("""
                INSERT INTO employees (name, phone, email, dept_id, rank_id)
                VALUES (:name, :phone, :email, :dept_id, :rank_id)
            """), {"name": name, "phone": phone, "email": email, "dept_id": dept_id, "rank_id": rank_id})

        flash("사원이 등록되었습니다.", "success")
        return redirect(url_for("admin_user_list"))

    # GET
    with engine.connect() as conn:
        depts = [r[0] for r in conn.execute(text("SELECT name FROM departments ORDER BY name")).all()]
        ranks = [r[0] for r in conn.execute(text("SELECT name FROM ranks ORDER BY name")).all()]
    return render_template("users/new.html", departments=depts, ranks=ranks)

@app.route("/admin/users/rank-dept", methods=["GET"], endpoint="admin_rank_dept_list")
def admin_rank_dept_list():
    with engine.connect() as conn:
        depts = [r[0] for r in conn.execute(text("SELECT name FROM departments ORDER BY name")).all()]
        ranks = [r[0] for r in conn.execute(text("SELECT name FROM ranks ORDER BY name")).all()]
    return render_template("users/rank-dept.html", departments=depts, ranks=ranks)


# ---------------------------------------------------------------------
# RUN
# ---------------------------------------------------------------------
ensure_tables()
print("DB URL:", DATABASE_URL)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
