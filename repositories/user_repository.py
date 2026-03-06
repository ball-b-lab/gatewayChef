from psycopg2.extras import RealDictCursor


class UserRepository:
    def __init__(self, connection):
        self.connection = connection

    def get_by_email(self, email):
        with self.connection.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, email, full_name, role, password_hash, created_at, updated_at
                FROM users
                WHERE lower(email) = lower(%s)
                """,
                (email,),
            )
            return cur.fetchone()

    def get_by_id(self, user_id):
        with self.connection.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, email, full_name, role, created_at, updated_at
                FROM users
                WHERE id = %s
                """,
                (user_id,),
            )
            return cur.fetchone()

    def create(self, email, password_hash, full_name=None, role="user"):
        with self.connection.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                INSERT INTO users (email, password_hash, full_name, role)
                VALUES (lower(%s), %s, %s, %s)
                RETURNING id, email, full_name, role, created_at, updated_at
                """,
                (email, password_hash, full_name, role),
            )
            return cur.fetchone()
