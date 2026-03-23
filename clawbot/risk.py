import time
from dataclasses import dataclass, field


@dataclass
class RiskManager:
    max_daily_loss: float = 100.0
    cooldown_seconds: float = 2.0

    daily_pnl: float = 0.0
    total_trades: int = 0
    total_wins: int = 0
    _last_trade_time: float = 0.0
    _traded_conditions: set = field(default_factory=set)
    _day_start: float = field(default_factory=time.time)

    def can_trade(self, condition_id: str) -> tuple[bool, str]:
        now = time.time()

        if now - self._day_start > 86400:
            self._reset_daily()

        if self.daily_pnl < -self.max_daily_loss:
            return False, "daily_loss_limit"

        if now - self._last_trade_time < self.cooldown_seconds:
            return False, "cooldown"

        if condition_id in self._traded_conditions:
            return False, "already_traded"

        return True, "ok"

    def record_trade(self, condition_id: str, pnl: float, won: bool):
        self._last_trade_time = time.time()
        self._traded_conditions.add(condition_id)
        self.daily_pnl += pnl
        self.total_trades += 1
        if won:
            self.total_wins += 1

    def _reset_daily(self):
        from .logger import log_trade
        log_trade(
            "daily_reset",
            trades=self.total_trades,
            wins=self.total_wins,
            pnl=round(self.daily_pnl, 2),
        )
        self.daily_pnl = 0.0
        self._traded_conditions.clear()
        self._day_start = time.time()

    @property
    def stats(self) -> dict:
        return {
            "total_trades": self.total_trades,
            "total_wins": self.total_wins,
            "daily_pnl": round(self.daily_pnl, 2),
            "win_rate": round(self.total_wins / max(1, self.total_trades) * 100, 1),
        }
