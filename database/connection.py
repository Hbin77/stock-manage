"""
데이터베이스 연결 및 세션 관리
SQLAlchemy 2.0 스타일의 세션 팩토리를 제공합니다.
"""
from contextlib import contextmanager
from typing import Generator

from loguru import logger
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from config.settings import settings
from database.models import Base


# 엔진 생성
# SQLite 사용 시 WAL 모드 활성화 → 읽기/쓰기 동시성 향상
_is_sqlite = "sqlite" in settings.DATABASE_URL

_engine_kwargs = dict(
    echo=False,           # SQL 로그 출력 여부 (디버깅 시 True)
    pool_pre_ping=True,   # 연결 유효성 사전 확인
)

if _is_sqlite:
    # 병렬 분석(ThreadPoolExecutor) 지원을 위해 StaticPool 대신 QueuePool 사용
    # StaticPool은 단일 연결 공유 → 스레드 간 동시 쓰기 충돌 발생
    _engine_kwargs.update(
        connect_args={"check_same_thread": False},
        pool_size=5,
        max_overflow=10,
    )
else:
    _engine_kwargs.update(
        pool_size=5,
        max_overflow=10,
        pool_recycle=3600,
    )

engine = create_engine(settings.DATABASE_URL, **_engine_kwargs)


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_conn, connection_record):
    """SQLite 전용: WAL 모드 및 외래 키 제약 활성화"""
    if "sqlite" in settings.DATABASE_URL:
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA wal_autocheckpoint=1000")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()


# 세션 팩토리
SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,  # 커밋 후 객체 재조회 방지 (성능 향상)
)


def _migrate_add_columns() -> None:
    """SQLAlchemy 모델 기준으로 기존 테이블에 누락된 컬럼을 자동 추가합니다."""
    if not _is_sqlite:
        return
    from sqlalchemy import inspect as sa_inspect

    inspector = sa_inspect(engine)
    with engine.connect() as conn:
        for table in Base.metadata.tables.values():
            if not inspector.has_table(table.name):
                continue
            existing_cols = {c["name"] for c in inspector.get_columns(table.name)}
            for col in table.columns:
                if col.name in existing_cols:
                    continue
                # SQLAlchemy 타입 → SQLite 타입 매핑
                col_type = col.type.compile(engine.dialect)
                try:
                    conn.execute(text(
                        f"ALTER TABLE {table.name} ADD COLUMN {col.name} {col_type}"
                    ))
                    conn.commit()
                    logger.info(f"[마이그레이션] {table.name}.{col.name} ({col_type}) 추가 완료")
                except Exception:
                    conn.rollback()


def init_db() -> None:
    """
    데이터베이스 초기화: 모든 테이블 생성
    이미 존재하는 테이블은 건드리지 않습니다 (checkfirst=True).
    """
    logger.info("데이터베이스 초기화 중...")
    Base.metadata.create_all(bind=engine, checkfirst=True)
    _migrate_add_columns()
    logger.success("데이터베이스 초기화 완료")


def drop_all_tables() -> None:
    """
    [주의] 모든 테이블 삭제 - 개발/테스트 환경에서만 사용
    """
    logger.warning("모든 테이블을 삭제합니다!")
    Base.metadata.drop_all(bind=engine)
    logger.info("테이블 삭제 완료")


@contextmanager
def get_db() -> Generator[Session, None, None]:
    """
    데이터베이스 세션 컨텍스트 매니저

    사용 예시:
        with get_db() as db:
            stocks = db.query(Stock).all()
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"DB 트랜잭션 오류, 롤백 처리: {e}")
        raise
    finally:
        db.close()


def check_connection() -> bool:
    """데이터베이스 연결 상태 확인"""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("데이터베이스 연결 정상")
        return True
    except Exception as e:
        logger.error(f"데이터베이스 연결 실패: {e}")
        return False
