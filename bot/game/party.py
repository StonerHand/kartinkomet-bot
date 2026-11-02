"""Games about the people in the chat: "who of us" polls, the bomb passed by reply, bets on life."""

from dataclasses import dataclass

from bot.game.types import Granted
from bot.rules import economy, party

WHO_RECENT_SECONDS = 14 * 86400  # whom a poll offers: the chat's players seen in two weeks


@dataclass(frozen=True)
class WhoResult:
    round: dict
    counts: dict[int, int]  # person → votes
    winners: list[int]  # the most votes; a tie: all of them, each gets the title
    granted: list[Granted]


@dataclass(frozen=True)
class BombResult:
    round: dict
    victim: int
    fine: int  # burned
    passers: list[int]  # everyone who passed it on, paid once each
    reward: int  # what each passer got
    granted: list[Granted]


@dataclass(frozen=True)
class BetResult:
    round: dict
    outcome: int  # 1 came true, 0 didn't, -1 called off (everyone got their stake back)
    payouts: dict[int, int]  # player → coins back (stake included)


class PartyMixin:
    # ── who of us ──────────────────────────────────────────────────────

    def start_who(
        self, chat_id: int, question: str, title: str, author: int | None = None, scheduled: bool = False
    ) -> tuple[str, dict | None]:
        """'started' | 'active' | 'cooldown' | 'shortage' | 'poor'. `author` asked a question of
        their own and pays for it; the daily poll is `scheduled` and skips the cooldown."""
        active = self.repo.open_rounds(chat_id, "who")
        if active:
            return "active", active[0]
        if not scheduled and author is None and self.who_cooldown_left(chat_id):
            return "cooldown", None
        people = self.repo.recent_members(chat_id, self.now() - WHO_RECENT_SECONDS, limit=party.WHO_OPTIONS)
        if len(people) < 2:
            return "shortage", None
        if author is not None and not self.repo.spend(author, self.who_question_price(), "who_question", self.now()):
            return "poor", None
        people = sorted(people, key=lambda _: self.rng.random())
        round_id = self.repo.create_round(
            chat_id, "who", self.now(), self.now() + party.WHO_SECONDS, author, f"{question}\n{title}", people
        )
        return "started", self.repo.get_round(round_id)

    def drop_round(self, round_id: str) -> None:
        """A round whose card never reached the chat: gone, and a paid question refunded."""
        found = self.repo.get_round(round_id)
        if found is None:
            return
        self.repo.drop_round(round_id)
        if found["kind"] == "who" and found["author"] is not None:
            self.repo.add_coins(found["author"], self.who_question_price(), "who_refund", self.now(), earn=False)

    def who_cooldown_left(self, chat_id: int) -> int:
        return max(0, party.WHO_COOLDOWN_SECONDS - (self.now() - self.repo.last_round_at(chat_id, "who")))

    def who_question_price(self) -> int:
        return self.scaled(party.WHO_QUESTION_PRICE)

    def vote_who(self, round_id: str, user_id: int, option: int) -> str:
        """'ok' | 'same' | 'closed' | 'gone'. Changing the vote is allowed."""
        found = self.repo.get_round(round_id)
        if found is None or found["kind"] != "who" or not 0 <= option < len(found["options"]):
            return "gone"
        if found["status"] != "open" or self.now() >= found["ends_at"]:
            return "closed"
        person = found["options"][option]
        if found["votes"].get(user_id, (None, 0))[0] == person:
            return "same"
        self.repo.put_round_vote(round_id, user_id, person)
        return "ok"

    def finish_who(self, round_id: str) -> WhoResult | None:
        """Close the poll: the people with the most votes wear its title for a day; every voter
        gets a vote's reward. Only the first call settles."""
        found = self.repo.get_round(round_id)
        if found is None or not self.repo.close_round(round_id, None):
            return None
        votes = {user: choice for user, (choice, _) in found["votes"].items()}
        counts = {person: 0 for person in found["options"]}
        for choice in votes.values():
            counts[choice] = counts.get(choice, 0) + 1
        winners = party.poll_winners(votes)
        title = found["text"].partition("\n")[2]
        for person in winners:
            self.repo.set_badge(person, "who", title, self.now() + party.BADGE_SECONDS)
            self.repo.incr_counter(person, "who_titles")
        for user_id in votes:
            self.pay(user_id, economy.VOTE, "vote")
        return WhoResult(found, counts, winners, self.check_achievements(list(votes)))

    # ── the bomb ───────────────────────────────────────────────────────

    def start_bomb(self, chat_id: int) -> tuple[str, dict | None]:
        """'started' | 'active' | 'cooldown' | 'shortage'. The bomb lands on a random player seen
        in the chat lately."""
        active = self.repo.open_rounds(chat_id, "bomb")
        if active:
            return "active", active[0]
        if self.bomb_cooldown_left(chat_id):
            return "cooldown", None
        people = self.repo.recent_members(chat_id, self.now() - party.BOMB_PLAYERS_SECONDS, limit=50)
        if len(people) < 2:
            return "shortage", None
        holder = people[self.rng.randrange(len(people))]
        fuse_at = self.now() + party.fuse(self.rng)
        ends_at = min(self.now() + party.BOMB_PASS_SECONDS, fuse_at)
        round_id = self.repo.create_round(chat_id, "bomb", self.now(), ends_at, holder=holder, fuse_at=fuse_at)
        return "started", self.repo.get_round(round_id)

    def bomb_cooldown_left(self, chat_id: int) -> int:
        return max(0, party.BOMB_COOLDOWN_SECONDS - (self.now() - self.repo.last_round_at(chat_id, "bomb")))

    def bomb_in(self, chat_id: int) -> dict | None:
        active = self.repo.open_rounds(chat_id, "bomb")
        return active[0] if active else None

    def pass_bomb(self, round_id: str, user_id: int, to: int) -> str:
        """'ok' | 'not_holder' | 'self' | 'closed' | 'gone'. The new holder gets their own
        BOMB_PASS_SECONDS, never past the hidden fuse."""
        found = self.repo.get_round(round_id)
        if found is None or found["kind"] != "bomb":
            return "gone"
        if found["status"] != "open" or self.now() >= found["ends_at"]:
            return "closed"
        if found["holder"] != user_id:
            return "not_holder"
        if to == user_id:
            return "self"
        ends_at = min(self.now() + party.BOMB_PASS_SECONDS, found["fuse_at"])
        if not self.repo.hand_over(round_id, user_id, to, ends_at):
            return "not_holder"
        passes = found["votes"].get(user_id, (0, 0))[0]
        self.repo.put_round_vote(round_id, user_id, passes + 1)
        return "ok"

    def finish_bomb(self, round_id: str) -> BombResult | None:
        """It goes off on whoever holds it: they lose BOMB_FINE (burned) and wear the shame for a
        day; everyone who passed it on is paid once. Only the first call settles."""
        found = self.repo.get_round(round_id)
        if found is None or not self.repo.close_round(round_id, found["holder"]):
            return None
        victim = found["holder"]
        fine = min(self.repo.player(victim)[0], self.reward(party.BOMB_FINE))
        if fine:
            self.repo.add_coins(victim, -fine, "bomb_fine", self.now(), earn=False)
        self.repo.set_badge(victim, "bomb", "Жертва бомбы", self.now() + party.BADGE_SECONDS)
        self.repo.incr_counter(victim, "bombs_blown")
        passers = [user for user in found["votes"] if user != victim]
        reward = 0
        for user_id in passers:
            reward = self.pay(user_id, party.BOMB_PASS_REWARD, "bomb_pass")
        return BombResult(found, victim, fine, passers, reward, self.check_achievements([victim, *passers]))

    # ── bets on life ───────────────────────────────────────────────────

    def open_bet(self, chat_id: int, author: int, claim: str) -> tuple[str, dict | None]:
        """'opened' | 'empty' | 'long' | 'too_many'."""
        claim = " ".join(claim.split())
        if not claim:
            return "empty", None
        if len(claim) > party.BET_CLAIM_MAX:
            return "long", None
        if len(self.repo.open_rounds(chat_id, "bet")) >= party.BET_OPEN_MAX:
            return "too_many", None
        ends_at = self.now() + party.BET_DAYS * 86400
        round_id = self.repo.create_round(chat_id, "bet", self.now(), ends_at, author, claim)
        return "opened", self.repo.get_round(round_id)

    def bet_stakes(self) -> list[int]:
        return [self.scaled(amount) for amount in party.BET_STAKES]

    def stake_bet(self, round_id: str, user_id: int, side: int, amount: int) -> str:
        """'ok' | 'author' | 'already' | 'poor' | 'closed' | 'gone'. One stake per player; the
        author judges the bet, so doesn't stake."""
        found = self.repo.get_round(round_id)
        if found is None or found["kind"] != "bet" or side not in (0, 1) or amount not in self.bet_stakes():
            return "gone"
        if found["status"] != "open":
            return "closed"
        if found["author"] == user_id:
            return "author"
        if user_id in found["votes"]:
            return "already"
        if not self.repo.spend(user_id, amount, "bet_stake", self.now()):
            return "poor"
        if not self.repo.put_round_vote(round_id, user_id, side, amount, replace=False):
            self.repo.add_coins(user_id, amount, "bet_refund", self.now(), earn=False)  # a double tap
            return "already"
        return "ok"

    def settle_bet(self, round_id: str, user_id: int | None, outcome: int) -> tuple[str, BetResult | None]:
        """'settled' | 'not_author' | 'closed' | 'gone'. The author says whether it came true
        (an admin can too); outcome -1 calls it off. user_id None: the bot itself (expiry)."""
        found = self.repo.get_round(round_id)
        if found is None or found["kind"] != "bet" or outcome not in (1, 0, -1):
            return "gone", None
        if found["status"] != "open":
            return "closed", None
        if user_id is not None and user_id != found["author"] and user_id not in self.admins:
            return "not_author", None
        if not self.repo.close_round(round_id, outcome):
            return "closed", None
        stakes = {user: (side, stake) for user, (side, stake) in found["votes"].items()}
        payouts = party.bet_payouts(stakes, outcome) if outcome != -1 else {u: s for u, (_, s) in stakes.items()}
        for player, coins in payouts.items():
            reason = "bet_win" if outcome != -1 and coins > stakes[player][1] else "bet_refund"
            self.repo.add_coins(player, coins, reason, self.now(), earn=False)
        return "settled", BetResult(self.repo.get_round(round_id), outcome, payouts)

    def expire_bets(self) -> list[BetResult]:
        """Bets nobody settled in BET_DAYS are called off: every stake goes back."""
        results = []
        for round_id in self.repo.due_rounds("bet", self.now()):
            status, result = self.settle_bet(round_id, None, -1)
            if result is not None:
                results.append(result)
        return results

    # ── badges ─────────────────────────────────────────────────────────

    def badges_of(self, user_id: int) -> list[tuple[str, str]]:
        """(kind, text) of the day-long titles the user wears."""
        return [(kind, text) for kind, text, _ in self.repo.badges_of(user_id, self.now())]
