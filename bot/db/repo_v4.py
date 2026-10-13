"""SQL for the v4 mechanics: bets, player challenges, bounties, bosses, marriages, titles.

A mixin of Repo: methods here use self.db and the base Repo helpers.
"""

import sqlite3
from uuid import uuid4


class V4Repo:
    db: sqlite3.Connection

    # ── arena bets ─────────────────────────────────────────────────────

    def place_bet(self, battle_id: str, user_id: int, slot: int, amount: int) -> None:
        with self.db:
            self.db.execute(
                "INSERT INTO battle_bets (battle_id, user_id, slot, amount) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(battle_id, user_id) DO UPDATE SET amount = amount + excluded.amount",
                (battle_id, user_id, slot, amount),
            )

    # ── challenges ─────────────────────────────────────────────────────

    def create_challenge(
        self, chat_id: int, from_user: int, to_user: int | None, stake: int, now: int, expires_at: int
    ) -> str:
        challenge_id = uuid4().hex[:12]
        with self.db:
            self.db.execute(
                "INSERT INTO challenges (id, chat_id, from_user, to_user, stake, created_at, expires_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (challenge_id, chat_id, from_user, to_user, stake, now, expires_at),
            )
        return challenge_id

    def get_challenge(self, challenge_id: str) -> dict | None:
        row = self.db.execute("SELECT * FROM challenges WHERE id = ?", (challenge_id,)).fetchone()
        return dict(row) if row else None

    def challenge_for_battle(self, battle_id: str) -> dict | None:
        row = self.db.execute("SELECT * FROM challenges WHERE battle_id = ?", (battle_id,)).fetchone()
        return dict(row) if row else None

    def pending_challenge_of(self, user_id: int) -> dict | None:
        row = self.db.execute(
            "SELECT * FROM challenges WHERE from_user = ? AND status = 'pending' LIMIT 1", (user_id,)
        ).fetchone()
        return dict(row) if row else None

    def pending_challenge_ids(self) -> list[str]:
        return [row[0] for row in self.db.execute("SELECT id FROM challenges WHERE status = 'pending'")]

    def set_challenge_message(self, challenge_id: str, message_id: int) -> None:
        with self.db:
            self.db.execute("UPDATE challenges SET message_id = ? WHERE id = ?", (message_id, challenge_id))

    def close_challenge(self, challenge_id: str, status: str, battle_id: str | None = None) -> bool:
        """pending → status, atomically. False if someone got there first."""
        with self.db:
            cursor = self.db.execute(
                "UPDATE challenges SET status = ?, battle_id = COALESCE(?, battle_id) "
                "WHERE id = ? AND status = 'pending'",
                (status, battle_id, challenge_id),
            )
        return cursor.rowcount == 1

    def accept_challenge(self, challenge_id: str, opponent: int) -> bool:
        with self.db:
            cursor = self.db.execute(
                "UPDATE challenges SET status = 'accepted', to_user = ? WHERE id = ? AND status = 'pending'",
                (opponent, challenge_id),
            )
        return cursor.rowcount == 1

    def active_challenge_battle(self, chat_id: int) -> str | None:
        row = self.db.execute(
            "SELECT id FROM battles WHERE chat_id = ? AND mode = 'challenge' AND status = 'active' LIMIT 1",
            (chat_id,),
        ).fetchone()
        return row[0] if row else None

    def set_challenge_battle(self, challenge_id: str, battle_id: str) -> None:
        with self.db:
            self.db.execute("UPDATE challenges SET battle_id = ? WHERE id = ?", (battle_id, challenge_id))

    # ── bounties ───────────────────────────────────────────────────────

    def add_bounty(self, pic_id: str, user_id: int, amount: int, now: int) -> int:
        with self.db:
            self.db.execute(
                "INSERT INTO bounties (pic_id, user_id, amount, at) VALUES (?, ?, ?, ?)",
                (pic_id, user_id, amount, now),
            )
        return self.bounty_on(pic_id)

    def bounty_on(self, pic_id: str) -> int:
        return self.db.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM bounties WHERE pic_id = ?", (pic_id,)
        ).fetchone()[0]

    def take_bounty(self, pic_id: str) -> int:
        """Remove and return the whole bounty on a pic."""
        with self.db:
            total = self.db.execute(
                "SELECT COALESCE(SUM(amount), 0) FROM bounties WHERE pic_id = ?", (pic_id,)
            ).fetchone()[0]
            self.db.execute("DELETE FROM bounties WHERE pic_id = ?", (pic_id,))
        return total

    # ── bosses ─────────────────────────────────────────────────────────

    def create_boss(
        self, chat_id: int, pic_id: str, title: str, hp: int, loot: int, now: int, ends_at: int
    ) -> str:
        boss_id = uuid4().hex[:12]
        with self.db:
            self.db.execute(
                "INSERT INTO bosses (id, chat_id, pic_id, title, hp, max_hp, loot, started_at, ends_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (boss_id, chat_id, pic_id, title, hp, hp, loot, now, ends_at),
            )
        return boss_id

    def get_boss(self, boss_id: str) -> dict | None:
        row = self.db.execute("SELECT * FROM bosses WHERE id = ?", (boss_id,)).fetchone()
        if row is None:
            return None
        boss = dict(row)
        boss["damage"] = {
            hit[0]: hit[1]
            for hit in self.db.execute(
                "SELECT user_id, damage FROM boss_hits WHERE boss_id = ? ORDER BY damage DESC", (boss_id,)
            )
        }
        return boss

    def active_boss(self, chat_id: int) -> dict | None:
        row = self.db.execute(
            "SELECT id FROM bosses WHERE status = 'active' AND chat_id = ? LIMIT 1", (chat_id,)
        ).fetchone()
        return self.get_boss(row[0]) if row else None

    def active_boss_ids(self) -> list[str]:
        return [row[0] for row in self.db.execute("SELECT id FROM bosses WHERE status = 'active'")]

    def last_boss_at(self, chat_id: int) -> int:
        row = self.db.execute("SELECT MAX(started_at) FROM bosses WHERE chat_id = ?", (chat_id,)).fetchone()
        return row[0] or 0

    def set_boss_message(self, boss_id: str, message_id: int) -> None:
        with self.db:
            self.db.execute("UPDATE bosses SET message_id = ? WHERE id = ?", (message_id, boss_id))

    def drop_boss(self, boss_id: str) -> None:
        with self.db:
            self.db.execute("DELETE FROM bosses WHERE id = ?", (boss_id,))

    def hit_boss(self, boss_id: str, user_id: int, damage: int) -> tuple[int, int] | None:
        """Apply damage to a live boss. Returns (hp left, total hits) or None if it's over."""
        with self.db:
            cursor = self.db.execute(
                "UPDATE bosses SET hp = MAX(0, hp - ?), hits = hits + 1, last_hit_by = ? "
                "WHERE id = ? AND status = 'active' AND hp > 0",
                (damage, user_id, boss_id),
            )
            if cursor.rowcount != 1:
                return None
            self.db.execute(
                "INSERT INTO boss_hits (boss_id, user_id, damage, hits) VALUES (?, ?, ?, 1) "
                "ON CONFLICT(boss_id, user_id) DO UPDATE SET damage = damage + excluded.damage, hits = hits + 1",
                (boss_id, user_id, damage),
            )
        row = self.db.execute("SELECT hp, hits FROM bosses WHERE id = ?", (boss_id,)).fetchone()
        return row[0], row[1]

    def add_boss_loot(self, boss_id: str, amount: int) -> None:
        with self.db:
            self.db.execute("UPDATE bosses SET loot = loot + ? WHERE id = ?", (amount, boss_id))

    def close_boss(self, boss_id: str, status: str) -> bool:
        with self.db:
            cursor = self.db.execute(
                "UPDATE bosses SET status = ? WHERE id = ? AND status = 'active'", (status, boss_id)
            )
        return cursor.rowcount == 1

    # ── marriages ──────────────────────────────────────────────────────

    def spouse_of(self, user_id: int) -> tuple[int, int] | None:
        """(spouse, since)."""
        row = self.db.execute("SELECT spouse_id, since FROM marriages WHERE user_id = ?", (user_id,)).fetchone()
        return (row[0], row[1]) if row else None

    def marry(self, first: int, second: int, now: int) -> bool:
        try:
            with self.db:
                self.db.execute("INSERT INTO marriages (user_id, spouse_id, since) VALUES (?, ?, ?)", (first, second, now))
                self.db.execute("INSERT INTO marriages (user_id, spouse_id, since) VALUES (?, ?, ?)", (second, first, now))
        except sqlite3.IntegrityError:
            return False
        return True

    def divorce(self, user_id: int) -> int | None:
        spouse = self.spouse_of(user_id)
        if spouse is None:
            return None
        with self.db:
            self.db.execute("DELETE FROM marriages WHERE user_id IN (?, ?)", (user_id, spouse[0]))
        return spouse[0]

    def create_proposal(self, chat_id: int, from_user: int, to_user: int, now: int) -> str:
        proposal_id = uuid4().hex[:12]
        with self.db:
            self.db.execute(
                "INSERT INTO proposals (id, chat_id, from_user, to_user, created_at) VALUES (?, ?, ?, ?, ?)",
                (proposal_id, chat_id, from_user, to_user, now),
            )
        return proposal_id

    def get_proposal(self, proposal_id: str) -> dict | None:
        row = self.db.execute("SELECT * FROM proposals WHERE id = ?", (proposal_id,)).fetchone()
        return dict(row) if row else None

    def close_proposal(self, proposal_id: str, status: str) -> bool:
        with self.db:
            cursor = self.db.execute(
                "UPDATE proposals SET status = ? WHERE id = ? AND status = 'pending'", (status, proposal_id)
            )
        return cursor.rowcount == 1

    # ── titles ─────────────────────────────────────────────────────────

    def title_of(self, user_id: int) -> str | None:
        row = self.db.execute("SELECT title FROM titles WHERE user_id = ?", (user_id,)).fetchone()
        return row[0] if row else None

    def set_title(self, user_id: int, title: str) -> None:
        with self.db:
            self.db.execute(
                "INSERT INTO titles (user_id, title) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET title = excluded.title",
                (user_id, title),
            )

    # ── players & pics helpers ─────────────────────────────────────────

    def take_counter(self, user_id: int, key: str) -> bool:
        """Decrement a counter if it's above zero (spending an inventory item). Atomic."""
        with self.db:
            cursor = self.db.execute(
                "UPDATE counters SET value = value - 1 WHERE user_id = ? AND key = ? AND value > 0",
                (user_id, key),
            )
        return cursor.rowcount == 1

    def forget_counters(self, prefix: str, keep_prefix: str) -> None:
        """Drop old per-day/per-week progress counters: keys starting with `prefix` but not
        with `keep_prefix` (the current day or week)."""
        with self.db:
            self.db.execute(
                "DELETE FROM counters WHERE key LIKE ? AND key NOT LIKE ?", (f"{prefix}%", f"{keep_prefix}%")
            )

    def forget_meta(self, prefix: str) -> None:
        with self.db:
            self.db.execute("DELETE FROM meta WHERE key LIKE ?", (f"{prefix}%",))

    def balances(self) -> list[tuple[int, int]]:
        return [(row[0], row[1]) for row in self.db.execute("SELECT user_id, coins FROM players")]

    def active_players(self, since: int) -> int:
        """People who did anything paid (votes, likes, games) since a time."""
        return self.db.execute(
            "SELECT COUNT(DISTINCT user_id) FROM ledger WHERE at >= ? AND earn = 1", (since,)
        ).fetchone()[0]

    def pics_of(self, owner_id: int, limit: int = 3, weakest: bool = False) -> list:
        order = "ASC" if weakest else "DESC"
        rows = self.db.execute(
            f"SELECT id FROM pics WHERE added_by = ? AND status = 'alive' ORDER BY rating {order}, id LIMIT ?",
            (owner_id, limit),
        ).fetchall()
        return [self.get_pic(row[0]) for row in rows]  # type: ignore[attr-defined]

    def set_rating(self, pic_id: str, rating: float) -> None:
        with self.db:
            self.db.execute("UPDATE pics SET rating = ? WHERE id = ?", (rating, pic_id))

    def user_by_name(self, name: str) -> int | None:
        clean = name.strip().lstrip("@").casefold()
        if not clean:
            return None
        row = self.db.execute(
            "SELECT user_id FROM users WHERE lower(username) = ? LIMIT 1", (clean,)
        ).fetchone()
        return row[0] if row else None
