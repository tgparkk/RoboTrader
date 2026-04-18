"""PostgreSQL connection pool 래퍼.

DatabaseManager의 pool/query boilerplate를 재사용 가능한 context manager로 분리.
기존 DatabaseManager public API를 깨지 않기 위해 wrapper 형태로 제공.
"""
from contextlib import contextmanager
from typing import Optional

import psycopg2
import psycopg2.extras
import psycopg2.pool

from utils.logger import setup_logger


class ConnectionPool:
    """psycopg2 ThreadedConnectionPool 래퍼 (프로세스 싱글톤).

    - `connection(commit=True)` context manager로 try/finally/commit/rollback 보일러플레이트 제거
    - 쿼리 헬퍼(`execute`, `fetchone`, `fetchall`) 제공
    """

    _instance: Optional['ConnectionPool'] = None

    def __init__(self, host: str, port: int, database: str, user: str, password: str):
        self.logger = setup_logger(__name__)
        self._host = host
        self._port = port
        self._database = database
        self._user = user
        self._password = password
        self._pool: Optional[psycopg2.pool.ThreadedConnectionPool] = None
        self._init_pool()

    # --- Singleton helpers ---------------------------------------------------
    @classmethod
    def get_or_create(cls, host: str, port: int, database: str, user: str, password: str) -> 'ConnectionPool':
        """싱글톤 인스턴스 반환. 풀이 닫혀 있으면 재생성."""
        if cls._instance is None or cls._instance._pool is None or cls._instance._pool.closed:
            cls._instance = cls(host, port, database, user, password)
        return cls._instance

    @classmethod
    def close_singleton(cls) -> None:
        """싱글톤 풀 닫기."""
        if cls._instance is not None:
            cls._instance.close()
            cls._instance = None

    # --- Pool lifecycle ------------------------------------------------------
    def _init_pool(self) -> None:
        if self._pool is None or self._pool.closed:
            try:
                self._pool = psycopg2.pool.ThreadedConnectionPool(
                    minconn=1,
                    maxconn=5,
                    host=self._host,
                    port=self._port,
                    database=self._database,
                    user=self._user,
                    password=self._password,
                    connect_timeout=10,
                )
                self.logger.info("PostgreSQL connection pool 초기화 완료")
            except Exception as e:
                self.logger.error(f"PostgreSQL connection pool 초기화 실패: {e}")
                raise

    @property
    def raw_pool(self) -> psycopg2.pool.ThreadedConnectionPool:
        """기존 코드 backward-compat용 raw pool 접근자."""
        if self._pool is None or self._pool.closed:
            self._init_pool()
        return self._pool

    def close(self) -> None:
        if self._pool is not None:
            try:
                self._pool.closeall()
            except Exception:
                pass
            self._pool = None

    # --- Connection management ----------------------------------------------
    def getconn(self):
        if self._pool is None or self._pool.closed:
            self._init_pool()
        return self._pool.getconn()

    def putconn(self, conn) -> None:
        if self._pool is not None and not self._pool.closed:
            self._pool.putconn(conn)

    @contextmanager
    def connection(self, commit: bool = False):
        """연결을 자동으로 반환하는 context manager.

        commit=True 이면 블록 종료 시 자동 commit, 예외 발생 시 rollback.
        commit=False 이면 단순 pool 반환만 수행 (read-only 쿼리).
        """
        conn = self.getconn()
        try:
            yield conn
            if commit:
                conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            self.putconn(conn)

    # --- Query helpers -------------------------------------------------------
    def execute(self, query: str, params: tuple = None) -> None:
        """INSERT/UPDATE/DELETE 실행 (자동 commit)."""
        with self.connection(commit=True) as conn:
            cur = conn.cursor()
            if params:
                cur.execute(query, params)
            else:
                cur.execute(query)

    def fetchone(self, query: str, params: tuple = None):
        with self.connection(commit=False) as conn:
            cur = conn.cursor()
            if params:
                cur.execute(query, params)
            else:
                cur.execute(query)
            return cur.fetchone()

    def fetchall(self, query: str, params: tuple = None):
        with self.connection(commit=False) as conn:
            cur = conn.cursor()
            if params:
                cur.execute(query, params)
            else:
                cur.execute(query)
            return cur.fetchall()
