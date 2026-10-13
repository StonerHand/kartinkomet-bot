"""Pic boss fights."""

from dataclasses import dataclass, field
from time import monotonic

from bot.core import boss as rules
from bot.services.types import Granted


@dataclass(frozen=True)
class HitResult:
    status: str  # ok | cooldown | broke | over | gone
    damage: int = 0
    crit: bool = False
    hp: int = 0
    counter_victim: int | None = None  # the boss struck back at this player
    killed: bool = False


@dataclass(frozen=True)
class BossReport:
    boss: dict
    won: bool
    payouts: dict[int, int] = field(default_factory=dict)
    top: int | None = None
    last_hit: int | None = None
    granted: list[Granted] = field(default_factory=list)


class BossMixin:
    _boss_hit_at: dict[tuple[str, int], float]

    def summon_boss(self, chat_id: int, title: str, double: bool = False, forced: bool = False) -> tuple[str, dict | None]:
        """('ok' | 'active' | 'cooldown' | 'shortage', boss). `forced` skips the cooldown (schedule, events)."""
        active = self.repo.active_boss(chat_id)
        if active:
            return "active", active
        if not forced and self.now() - self.repo.last_boss_at(chat_id) < rules.SUMMON_COOLDOWN_SECONDS:
            return "cooldown", None
        legends = self.repo.top_rated(30)
        pool = legends or self.repo.random_alive(1)
        if not pool:
            return "shortage", None
        pic = pool[self.rng.randrange(len(pool))]
        players = self.repo.active_players(self.now() - 7 * 86400)
        hp = rules.max_hp(players, double)
        boss_id = self.repo.create_boss(
            chat_id, pic.id, title, hp, rules.loot(hp, double), self.now(), self.now() + rules.DURATION_SECONDS
        )
        return "ok", self.repo.get_boss(boss_id)

    def boss_cooldown_left(self, chat_id: int) -> int:
        return max(0, rules.SUMMON_COOLDOWN_SECONDS - (self.now() - self.repo.last_boss_at(chat_id)))

    def hit_boss(self, boss_id: str, user_id: int, super_hit: bool = False) -> HitResult:
        boss = self.repo.get_boss(boss_id)
        if boss is None:
            return HitResult("gone")
        if boss["status"] != "active" or boss["hp"] <= 0 or self.now() >= boss["ends_at"]:
            return HitResult("over", hp=boss["hp"])
        key = (boss_id, user_id)
        moment = monotonic()
        if not super_hit and moment - self._boss_hit_at.get(key, 0.0) < rules.HIT_COOLDOWN_SECONDS:
            return HitResult("cooldown", hp=boss["hp"])
        if super_hit:
            if not self.repo.spend(user_id, rules.SUPER_PRICE, "boss_super", self.now()):
                return HitResult("broke", hp=boss["hp"])
            self.repo.add_boss_loot(boss_id, rules.SUPER_PRICE)
        self._boss_hit_at[key] = moment
        blow = rules.hit(self.rng, super_hit)
        applied = self.repo.hit_boss(boss_id, user_id, blow.damage)
        if applied is None:
            if super_hit:
                self.repo.add_coins(user_id, rules.SUPER_PRICE, "boss_refund", self.now(), earn=False)
            return HitResult("over", hp=0)
        hp, hits = applied
        self.progress(user_id, "boss_hit")
        self.progress(user_id, "boss_damage", blow.damage)
        victim = None
        if hp > 0 and hits % rules.COUNTER_EVERY == 0:
            fighters = list(self.repo.get_boss(boss_id)["damage"])
            victim = fighters[self.rng.randrange(len(fighters))] if fighters else None
            if victim is not None:
                taken = min(rules.COUNTER_FINE, self.repo.player(victim)[0])
                if taken and self.repo.spend(victim, taken, "boss_counter", self.now()):
                    self.repo.add_boss_loot(boss_id, taken)
        return HitResult("ok", blow.damage, blow.crit, hp, victim, killed=hp == 0)

    def finish_boss(self, boss_id: str) -> BossReport | None:
        boss = self.repo.get_boss(boss_id)
        if boss is None or boss["status"] != "active":
            return None
        won = boss["hp"] <= 0
        if not self.repo.close_boss(boss_id, "won" if won else "lost"):
            return None
        boss = self.repo.get_boss(boss_id)
        damage = boss["damage"]
        if not won:
            self.repo.shift_rating(boss["pic_id"], rules.ESCAPE_RATING_BONUS)
            return BossReport(boss, False, granted=self.check_achievements(list(damage)))
        payouts = rules.split_loot(boss["loot"], damage)
        last = boss["last_hit_by"]
        if isinstance(last, int):
            payouts[last] = payouts.get(last, 0) + rules.LAST_HIT_BONUS
        for user_id, amount in payouts.items():
            self.pay(user_id, amount, "boss")
        events: dict[int, list[str]] = {}
        for user_id in damage:
            self.repo.incr_counter(user_id, "bosses_beaten")
        top = next(iter(damage), None)  # ordered by damage
        if top is not None:
            events.setdefault(top, []).append("boss_slayer")
            self.grant_chest(top, "rare")
        if isinstance(last, int):
            events.setdefault(last, []).append("last_hit")
        return BossReport(boss, True, payouts, top, last, self.check_achievements(list(damage), events))
