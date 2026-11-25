"""004: призовой фонд состязания."""

import psycopg


def upgrade(connection: psycopg.Connection) -> None:
    connection.execute(
        """
        ALTER TABLE competitions
        ADD COLUMN prize_fund_rub BIGINT NOT NULL DEFAULT 0
            CHECK (prize_fund_rub >= 0)
        """
    )
