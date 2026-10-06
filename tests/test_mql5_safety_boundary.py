from __future__ import annotations

import re
import unittest
from pathlib import Path


SCRIPTS = tuple(
    sorted((Path(__file__).resolve().parents[1] / "mt5" / "Scripts").glob("*.mq5"))
)


class MQL5SafetyBoundaryTests(unittest.TestCase):
    def test_scripts_cannot_trade_or_export_sensitive_account_data(self) -> None:
        self.assertTrue(SCRIPTS, "No MQL5 scripts were found")
        forbidden = {
            "synchronous order submission": r"\bOrderSend\s*\(",
            "asynchronous order submission": r"\bOrderSendAsync\s*\(",
            "trade request construction": r"\bMqlTradeRequest\b",
            "standard trading library": r"#include\s*[<\"]Trade/",
            "trade wrapper": r"\bCTrade\b",
            "position closure": r"\bPositionClose\s*\(",
            "account login": r"\bACCOUNT_LOGIN\b",
            "account holder name": r"\bACCOUNT_NAME\b",
            "account balance": r"\bACCOUNT_BALANCE\b",
            "account equity": r"\bACCOUNT_EQUITY\b",
            "account margin": r"\bACCOUNT_MARGIN\b",
        }

        for script in SCRIPTS:
            source = script.read_text(encoding="utf-8")
            for capability, pattern in forbidden.items():
                with self.subTest(script=script.name, capability=capability):
                    self.assertIsNone(
                        re.search(pattern, source, flags=re.IGNORECASE),
                        f"{script.name} crossed the read-only boundary: {capability}",
                    )


if __name__ == "__main__":
    unittest.main()
