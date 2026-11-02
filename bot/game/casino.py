"""Casino on Telegram dice and parimutuel bets on battles."""

from dataclasses import dataclass

from bot.core import casino
from bot.services.types import Granted

SPORTS = ("dice", "darts", "basket", "football", "bowling")
ALL_IN_MIN = 300
HIGH_ROLLER_WIN = 2000


@dataclass(frozen=True)
class CasinoResult:
    game: str
    stake: int
    roll: casino.Roll
    payout: int
    balance: int
    granted: list[Granted]

    @property
    def profit(self) -> int:
        return self.payout - self.stake


class CasinoMixin:
    def set_stake(self, user_id: int, amount: int | None) -> None:
        """A fixed stake (a number typed after a command); None means all-in: every game takes
        the whole balance until something else is chosen."""
        self.repo.set_counter(user_id, "stake_all", int(amount is None))
        self.repo.set_counter(user_id, "stake_share", 0)
        if amount is not None:
            self.repo.set_counter(user_id, "stake", max(casino.STAKE_MIN, amount))

    def set_stake_share(self, user_id: int, share: int) -> None:
        """Stake a share of whatever the balance is at the moment of each game."""
        self.repo.set_counter(user_id, "stake_all", 0)
        self.repo.set_counter(user_id, "stake", 0)
        self.repo.set_counter(user_id, "stake_share", share)

    def stake_mode(self, user_id: int) -> tuple[str, int]:
        """('all', 0) | ('share', percent) | ('fixed', coins). Newcomers stake DEFAULT_SHARE."""
        if self.repo.counter(user_id, "stake_all"):
            return "all", 0
        fixed = self.repo.counter(user_id, "stake")
        share = self.repo.counter(user_id, "stake_share")
        if fixed and not share:
            return "fixed", fixed
        return "share", share or casino.DEFAULT_SHARE

    def stake_for_play(self, user_id: int) -> int:
        mode, value = self.stake_mode(user_id)
        balance = self.repo.player(user_id)[0]
        if mode == "all":
            return balance
        if mode == "share":
            return casino.share_stake(balance, value)
        return value

    def place_casino_bet(self, user_id: int, stake: int) -> str:
        """'ok' | 'small' | 'broke'. Takes the stake up front."""
        balance = self.repo.player(user_id)[0]
        if stake < casino.STAKE_MIN:
            return "broke" if balance < casino.STAKE_MIN else "small"
        if not self.repo.spend(user_id, stake, "casino_bet", self.now()):
            return "broke"
        self.repo.set_counter(user_id, "casino_all_in", int(stake == balance and stake >= ALL_IN_MIN))
        return "ok"

    def refund_casino_bet(self, user_id: int, stake: int) -> None:
        self.repo.add_coins(user_id, stake, "casino_refund", self.now(), earn=False)

    def settle_casino(self, user_id: int, game: str, stake: int, values: tuple[int, ...]) -> CasinoResult:
        if game == "dice":
            roll = casino.dice_duel(values[0], values[1])
        else:
            roll = casino.SINGLE_ROLL[game](values[0])
        payout = casino.payout(stake, roll, lucky=self.day_is("lucky_day"))
        if payout:
            self.repo.add_coins(user_id, payout, "casino_win", self.now(), earn=False)
        events: list[str] = []
        self.repo.incr_counter(user_id, "casino_bets")
        self.progress(user_id, "casino_bet")
        if payout > stake:
            self.repo.incr_counter(user_id, "casino_wins")
            self.progress(user_id, "casino_win")
            if game in SPORTS:
                mask = self.repo.counter(user_id, "sports_won") | (1 << SPORTS.index(game))
                self.repo.set_counter(user_id, "sports_won", mask)
            if payout - stake >= HIGH_ROLLER_WIN:
                events.append("high_roller")
        if game == "slots" and roll.kind == "jackpot":
            events.append("triple_seven")
        if game == "darts" and roll.kind == "bull":
            self.repo.incr_counter(user_id, "bullseyes")
        if self.repo.counter(user_id, "casino_all_in"):
            events.append("all_in")
        balance = self.repo.player(user_id)[0]
        if balance == 0:
            events.append("bankrupt")
        return CasinoResult(game, stake, roll, payout, balance, self.check_achievements([user_id], {user_id: events}))

    # ── arena bets ─────────────────────────────────────────────────────

    def bet_battle(self, battle_id: str, user_id: int, slot: int) -> tuple[str, int]:
        """Raise your bet on a slot by one step (BET_STEP, scaled with the chat's wealth). ('ok' | 'gone' | 'closed' | 'other_slot' |
        'max' | 'broke' | 'fighter', your total on the battle)."""
        battle = self.repo.get_battle(battle_id)
        if battle is None or not 0 <= slot < len(battle.pics):
            return "gone", 0
        if battle.status != "active" or self.now() >= battle.ends_at:
            return "closed", 0
        if battle.mode == "challenge":
            challenge = self.repo.challenge_for_battle(battle_id)
            if challenge and user_id in (challenge["from_user"], challenge["to_user"]):
                return "fighter", 0
        current = battle.bets.get(user_id)
        if current and current[0] != slot:
            return "other_slot", current[1]
        already = current[1] if current else 0
        step = self.bet_step()
        if already + step > self.bet_max():
            return "max", already
        if not self.repo.spend(user_id, step, "bet", self.now()):
            return "broke", already
        self.repo.place_bet(battle_id, user_id, slot, step)
        if not current:
            self.progress(user_id, "arena_bet")
        return "ok", already + step

    def _settle_bets(self, battle, winner: int | None, counted: bool) -> tuple[dict[int, tuple[int, int]], int]:
        """Pay out bets. Returns (user → (staked, paid), coins burned)."""
        if not battle.bets:
            return {}, 0
        paid = casino.settle_bets(battle.bets, winner if counted else None)
        pool = sum(amount for _, amount in battle.bets.values())
        odds = casino.odds(battle.bet_pool())
        result = {}
        for user_id, (slot, amount) in battle.bets.items():
            back = paid.get(user_id, 0)
            result[user_id] = (amount, back)
            if back:
                reason = "bet_win" if counted and winner is not None else "bet_refund"
                self.repo.add_coins(user_id, back, reason, self.now(), earn=False)
            if counted and winner is not None and slot == winner:
                self.repo.incr_counter(user_id, "bets_won")
                self.progress(user_id, "bet_won")
                if (odds[slot] or 0) >= 5:
                    self._pending_events.setdefault(user_id, []).append("dark_horse")
        return result, pool - sum(paid.values())
