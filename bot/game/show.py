"""The evening show: a bank heist the chat plans together, the big cup of eight pics."""

import json
from dataclasses import dataclass

from bot.game.types import Granted
from bot.models.records import Battle, Pic
from bot.rules import deck, shop, show


@dataclass(frozen=True)
class HeistStep:
    round: dict
    kind: str  # stage (the next one starts) | cancelled | busted | clean
    event: str | None = None  # the stage just played
    option: int | None = None  # what the crew chose there
    success: bool = False
    loot: int = 0  # each member's share of a clean job
    crew: tuple[int, ...] = ()
    granted: tuple[Granted, ...] = ()


@dataclass(frozen=True)
class CupStep:
    round: dict
    kind: str  # match (a duel to launch) | champion
    battle: Battle | None = None
    champion: Pic | None = None
    prize: int = 0


def state_of(found: dict) -> dict:
    return json.loads(found["text"] or "{}")


class ShowMixin:
    def _show_done_today(self, kind: str, chat_id: int) -> bool:
        return self.repo.meta_int(f"show:{kind}:{chat_id}") == self.local_day()

    # ── the heist ──────────────────────────────────────────────────────

    def start_heist(self, chat_id: int) -> tuple[str, dict | None]:
        """'started' | 'active' | 'done_today'. Recruiting first: RECRUIT_SECONDS to join."""
        active = self.repo.open_rounds(chat_id, "heist")
        if active:
            return "active", active[0]
        if self._show_done_today("heist", chat_id):
            return "done_today", None
        self.repo.set_meta(f"show:heist:{chat_id}", self.local_day())
        state = {"stage": 0, "events": show.plan(self.rng), "log": []}
        round_id = self.repo.create_round(
            chat_id, "heist", self.now(), self.now() + show.RECRUIT_SECONDS, text=json.dumps(state)
        )
        return "started", self.repo.get_round(round_id)

    def join_heist(self, round_id: str, user_id: int) -> str:
        """'ok' | 'already' | 'full' | 'started' | 'jailed' | 'gone'."""
        found = self.repo.get_round(round_id)
        if found is None or found["kind"] != "heist" or found["status"] != "open":
            return "gone"
        if state_of(found)["stage"] or self.now() >= found["ends_at"]:
            return "started"
        if user_id in found["votes"]:
            return "already"
        if len(found["votes"]) >= show.MAX_CREW:
            return "full"
        if self.repo.counter(user_id, "jail_until") > self.now():
            return "jailed"
        if not self.repo.put_round_vote(round_id, user_id, -1, len(found["votes"]), replace=False):
            return "already"
        return "ok"

    def vote_heist(self, round_id: str, user_id: int, option: int) -> str:
        """'ok' | 'same' | 'not_crew' | 'closed' | 'gone'."""
        found = self.repo.get_round(round_id)
        if found is None or found["kind"] != "heist" or option not in (0, 1):
            return "gone"
        if found["status"] != "open" or not state_of(found)["stage"] or self.now() >= found["ends_at"]:
            return "closed"
        if user_id not in found["votes"]:
            return "not_crew"
        choice, role = found["votes"][user_id]
        if choice == option:
            return "same"
        self.repo.put_round_vote(round_id, user_id, option, role)
        return "ok"

    def heist_crew(self, found: dict) -> list[tuple[int, str]]:
        """(member, role) in the order they joined."""
        return [(user, show.role_of(role)) for user, (_, role) in sorted(found["votes"].items(), key=lambda v: v[1][1])]

    def advance_heist(self, round_id: str) -> HeistStep | None:
        """When the phase's time is up: recruiting ends (too few: called off), or the crew's
        choice plays out — a failure busts everyone, the last success pays the loot."""
        found = self.repo.get_round(round_id)
        if found is None or found["status"] != "open" or self.now() < found["ends_at"]:
            return None
        state = state_of(found)
        crew = [user for user, _ in self.heist_crew(found)]
        if state["stage"] == 0:
            if len(crew) < show.MIN_CREW:
                self.repo.close_round(round_id, -1)
                return HeistStep(self.repo.get_round(round_id), "cancelled", crew=tuple(crew))
            state["stage"] = 1
            self.repo.update_round(round_id, self.now() + show.STAGE_SECONDS, json.dumps(state))
            return HeistStep(self.repo.get_round(round_id), "stage", crew=tuple(crew))
        event = state["events"][state["stage"] - 1]
        option = show.chosen([choice for choice, _ in found["votes"].values() if choice in (0, 1)], self.rng)
        roles = {role for _, role in self.heist_crew(found)}
        success = self.rng.random() < show.chance(show.EVENTS[event][option], roles)
        state["log"].append([event, option, success])
        if not success:
            self.repo.update_round(round_id, found["ends_at"], json.dumps(state))
            self.repo.close_round(round_id, 0)
            for user_id in crew:
                self.repo.set_counter(user_id, "jail_until", self.now() + shop.JAIL_SECONDS)
            return HeistStep(self.repo.get_round(round_id), "busted", event, option, False, crew=tuple(crew))
        if state["stage"] == show.STAGES:
            self.repo.update_round(round_id, found["ends_at"], json.dumps(state))
            self.repo.close_round(round_id, 1)
            loot = 0
            for user_id in crew:
                loot = self.pay(user_id, show.LOOT_PER_MEMBER, "heist")
                self.repo.incr_counter(user_id, "heists_clean")
            granted = tuple(self.check_achievements(crew))
            return HeistStep(self.repo.get_round(round_id), "clean", event, option, True, loot, tuple(crew), granted)
        state["stage"] += 1
        self.repo.update_round(round_id, self.now() + show.STAGE_SECONDS, json.dumps(state))
        self.repo.clear_round_choices(round_id)
        return HeistStep(self.repo.get_round(round_id), "stage", event, option, True, crew=tuple(crew))

    # ── the big cup ────────────────────────────────────────────────────

    def start_cup(self, chat_id: int) -> tuple[str, dict | None]:
        """'started' | 'active' | 'done_today' | 'shortage'. Eight pics from the chat's deck, a
        bracket of duels; the schedule's tick launches each match (cup_step)."""
        active = self.repo.open_rounds(chat_id, "cup")
        if active:
            return "active", active[0]
        if self._show_done_today("cup", chat_id):
            return "done_today", None
        drawn = deck.draw_many(self.repo, deck.scope_of(chat_id), self.now(), show.CUP_SIZE)
        if len(drawn) < show.CUP_SIZE:
            return "shortage", None
        self.repo.set_meta(f"show:cup:{chat_id}", self.local_day())
        state = {"alive": [pic.id for pic, _ in drawn], "next": [], "size": show.CUP_SIZE, "battle": None}
        round_id = self.repo.create_round(chat_id, "cup", self.now(), self.now() + 6 * 3600, text=json.dumps(state))
        return "started", self.repo.get_round(round_id)

    def cup_stage(self, size: int) -> str:
        return show.CUP_ROUNDS.get(size, "матч")

    def cup_step(self, round_id: str) -> CupStep | None:
        """Move the cup on: None while its match is still being voted. A finished match sends its
        winner on (a draw: the higher rating); then the next pair gets a duel, or the last pic
        standing is the champion."""
        found = self.repo.get_round(round_id)
        if found is None or found["kind"] != "cup" or found["status"] != "open":
            return None
        state = state_of(found)
        if state["battle"]:
            battle = self.repo.get_battle(state["battle"])
            if battle is not None and battle.status == "active":
                return None
            if battle is not None and battle.winner_slot is not None:
                winner = battle.pics[battle.winner_slot].id
            else:  # a draw, or a match whose card never went out: the higher rating goes on
                pair = [pic for pic in (self.repo.get_pic(pic_id) for pic_id in state["pair"]) if pic is not None]
                winner = max(pair, key=lambda pic: pic.rating).id if pair else None
            if winner is not None:
                state["next"].append(winner)
            state["battle"] = None
        if not state["alive"]:
            if len(state["next"]) <= 1:
                self.repo.update_round(round_id, found["ends_at"], json.dumps(state))
                self.repo.close_round(round_id, 0)
                champion = self.repo.get_pic(state["next"][0]) if state["next"] else None
                prize = 0
                if champion is not None:
                    self.repo.shift_rating(champion.id, show.CUP_RATING_BONUS)
                    if champion.added_by is not None:
                        prize = self.pay(champion.added_by, show.CUP_PRIZE, "cup")
                        self.repo.incr_counter(champion.added_by, "cups_won")
                return CupStep(self.repo.get_round(round_id), "champion", champion=champion, prize=prize)
            state["alive"], state["next"], state["size"] = state["next"], [], len(state["next"])
        pair, state["alive"] = state["alive"][:2], state["alive"][2:]
        stage = self.cup_stage(state["size"])
        battle_id = self.repo.create_battle(
            "duel", found["chat_id"], pair, self.now(), show.CUP_DUEL_SECONDS, title=f"Кубок · {stage}", mode="cup"
        )
        state["battle"], state["pair"] = battle_id, pair
        self.repo.update_round(round_id, found["ends_at"], json.dumps(state))
        return CupStep(self.repo.get_round(round_id), "match", battle=self.repo.get_battle(battle_id))

    def open_cup_ids(self) -> list[str]:
        return self.repo.open_round_ids(("cup",))
