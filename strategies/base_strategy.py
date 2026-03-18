from typing import Tuple
from config.settings import settings

class BaseStrategy:
    """
    A base class for trading strategies, containing shared logic for risk management.
    """
    def _get_sl_tp_settings(self, pair: str) -> Tuple[float, float]:
        """
        Returns (sl_atr_mult, tp_atr_mult) based on pair specific settings or global defaults.
        This logic is shared across multiple strategies.
        """
        sl_mult = settings.ATR_MULTIPLIER_SL
        tp_mult = settings.ATR_MULTIPLIER_TP
        
        if "Volatility 75" in pair or "Vol 75" in pair or "R_75" in pair:
            sl_mult = settings.VOL75_SL_ATR_MULT
            tp_mult = settings.VOL75_TP_ATR_MULT
        elif "Volatility 25" in pair or "Vol 25" in pair or "R_25" in pair:
            sl_mult = settings.VOL25_SL_ATR_MULT
            tp_mult = settings.VOL25_TP_ATR_MULT
        elif "Volatility 10" in pair or "Vol 10" in pair or "R_10" in pair:
            sl_mult = settings.VOL10_SL_ATR_MULT
            tp_mult = settings.VOL10_TP_ATR_MULT
            
        return sl_mult, tp_mult