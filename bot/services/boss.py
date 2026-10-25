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
    fine: int = 0  # coins the counterattack took from the victim
    phase: str = "calm"  # the raid phase this hit landed in


@dataclass(frozen=True)
class BossReport:
    boss: dict
    won: bool
    payouts: dict[int, int] = field(default_factory=dict)
    top: int | None = None
    last_hit: int | None = None
    granted: list[Granted] = field(default_factory=list)
    chests: int = 0  # raids: wooden chests handed to everyone who dealt RAID_CHEST_DAMAGE
    last_hit_bonus: int = 0


class BossMixin:
    _boss_hit_at: dict[tuple[str, int], float]

    def summon_boss(
        self, chat_id: int, title: str, double: bool = False, forced: bool = False, raid: bool = False
    ) -> tuple[str, dict | None]:
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
        loot = self.scaled(rules.loot(hp, double))  # a pool of money that grows like everything else
        duration = rules.DURATION_SECONDS
        if raid:
            hp, loot, duration = hp * rules.RAID_HP_FACTOR, loot * rules.RAID_LOOT_FACTOR, rules.RAID_SECONDS
        boss_id = self.repo.create_boss(chat_id, pic.id, title, hp, loot, self.now(), self.now() + duration, raid)
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
        price = self.super_price()
        if super_hit:
            if not self.repo.spend(user_id, price, "boss_super", self.now()):
                return HitResult("broke", hp=boss["hp"])
            self.repo.add_boss_loot(boss_id, price)
        self._boss_hit_at[key] = moment
        current = rules.phase(boss["hp"], boss["max_hp"], bool(boss["raid"]))
        blow = rules.hit(self.rng, super_hit, current)
        applied = self.repo.hit_boss(boss_id, user_id, blow.damage, self.now())
        if applied is None:
            if super_hit:
                self.repo.add_coins(user_id, price, "boss_refund", self.now(), earn=False)
            return HitResult("over", hp=0)
        hp, hits = applied
        self.progress(user_id, "boss_hit")
        self.progress(user_id, "boss_damage", blow.damage)
        victim, taken = None, 0
        enraged = current in ("rage", "shield")
        every = rules.RAGE_COUNTER_EVERY if enraged else rules.COUNTER_EVERY
        if hp > 0 and hits % every == 0:
            fighters = list(self.repo.get_boss(boss_id)["damage"])
            victim = fighters[self.rng.randrange(len(fighters))] if fighters else None
            if victim is not None:
                fine = self.scaled(rules.COUNTER_FINE) * (2 if enraged else 1)
                taken = min(fine, self.repo.player(victim)[0])
                if taken and self.repo.spend(victim, taken, "boss_counter", self.now()):
                    self.repo.add_boss_loot(boss_id, taken)
                else:
                    taken = 0
        return HitResult("ok", blow.damage, blow.crit, hp, victim, killed=hp == 0, fine=taken, phase=current)

    def heal_idle_raid(self, boss_id: str) -> int:
        """A raid boss nobody hit for HEAL_IDLE_SECONDS regains HEAL_SHARE of its health.
        Returns the hp healed (0 most of the time)."""
        boss = self.repo.get_boss(boss_id)
        if boss is None or not boss["raid"] or boss["status"] != "active" or boss["hp"] <= 0:
            return 0
        if self.now() - (boss["last_hit_at"] or boss["started_at"]) < rules.HEAL_IDLE_SECONDS:
            return 0
        amount = max(1, int(boss["max_hp"] * rules.HEAL_SHARE))
        return self.repo.heal_boss(boss_id, amount, self.now()) - boss["hp"]

    def finish_boss(self, boss_id: str) -> BossReport | None:
        boss = self.repo.get_boss(boss_id)
        if boss is None or boss["status"] != "active":
            return None
        won = boss["hp"] <= 0
        if not self.repo.close_boss(boss_id, "won" if won else "lost"):
            return None
        boss = self.repo.get_boss(boss_id)
        damage = boss["damage"]
        for key in [key for key in self._boss_hit_at if key[0] == boss_id]:
            del self._boss_hit_at[key]
        if not won:
            self.repo.shift_rating(boss["pic_id"], rules.ESCAPE_RATING_BONUS)
            return BossReport(boss, False, granted=self.check_achievements(list(damage)))
        payouts = rules.split_loot(boss["loot"], damage)
        last = boss["last_hit_by"]
        bonus = self.scaled(rules.LAST_HIT_BONUS)
        if isinstance(last, int):
            payouts[last] = payouts.get(last, 0) + bonus
        for user_id, amount in payouts.items():
            self.pay(user_id, amount, "boss")
        events: dict[int, list[str]] = {}
        for user_id in damage:
            self.repo.incr_counter(user_id, "bosses_beaten")
        top = next(iter(damage), None)  # ordered by damage
        if top is not None:
            events.setdefault(top, []).append("boss_slayer")
            self.grant_chest(top, "legend" if boss["raid"] else "rare")
        chests = 0
        if boss["raid"]:
            for user_id, dealt in damage.items():
                if dealt >= rules.RAID_CHEST_DAMAGE and user_id != top:
                    self.grant_chest(user_id, "wood")
                    chests += 1
        if isinstance(last, int):
            events.setdefault(last, []).append("last_hit")
        granted = self.check_achievements(list(damage), events)
        return BossReport(boss, True, payouts, top, last, granted, chests, bonus)
