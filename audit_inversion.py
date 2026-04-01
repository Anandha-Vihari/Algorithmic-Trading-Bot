"""
SIGNAL INVERSION AUDIT & VERIFICATION

Comprehensive tests to validate:
1. Direction inversion correctness (BUY↔SELL)
2. TP/SL swap validation
3. Distance consistency (entry to TP/SL distances mirror correctly)
4. Integration correctness (execution layer only)
5. Edge case handling
6. Logging accuracy
"""

from signal_manager import Signal
from signal_inverter import invert_signal, validate_inverted_levels
from datetime import datetime, timezone


class InversionAudit:
    """Audit suite for signal inversion."""

    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.errors = []

    def test(self, name: str, condition: bool, details: str = ""):
        """Record test result."""
        status = "PASS" if condition else "FAIL"
        print(f"  [{status}] {name}")
        if details:
            print(f"         {details}")

        if condition:
            self.passed += 1
        else:
            self.failed += 1
            self.errors.append(f"{name}: {details}")

    def assert_equal(self, actual, expected, name: str):
        """Assert equality."""
        match = abs(actual - expected) < 0.00001 if isinstance(actual, float) else actual == expected
        self.test(name, match, f"Expected {expected}, got {actual}")

    def assert_true(self, condition, name: str, details: str = ""):
        """Assert condition is true."""
        self.test(name, condition, details)

    def summary(self):
        """Print summary."""
        total = self.passed + self.failed
        print(f"\n{'='*80}")
        print(f"AUDIT SUMMARY: {self.passed}/{total} passed")
        if self.failed > 0:
            print(f"\n⚠ FAILURES ({self.failed}):")
            for error in self.errors:
                print(f"  - {error}")
        print(f"{'='*80}\n")
        return self.failed == 0


# ══════════════════════════════════════════════════════════════════════════════
# TEST SUITE
# ══════════════════════════════════════════════════════════════════════════════

def create_signal(pair: str, side: str, open_price: float, tp: float, sl: float) -> Signal:
    """Helper to create test signals."""
    return Signal(
        pair=pair,
        side=side,
        open_price=open_price,
        tp=tp,
        sl=sl,
        time=datetime.now(timezone.utc),
        frame="short",
        status="ACTIVE"
    )


def test_direction_inversion():
    """Test 1: Direction Inversion Correctness"""
    print("\n" + "="*80)
    print("TEST 1: DIRECTION INVERSION")
    print("="*80)

    audit = InversionAudit()

    # Test 1a: BUY -> SELL
    print("\n[1a] BUY should become SELL:")
    sig = create_signal("EURUSD", "BUY", 1.2000, 1.2100, 1.1950)
    inverted, metadata = invert_signal(sig, True)

    audit.test(
        "Direction flipped BUY->SELL",
        inverted.side == "SELL",
        f"Got {inverted.side}"
    )

    # Test 1b: SELL -> BUY
    print("\n[1b] SELL should become BUY:")
    sig = create_signal("GBPUSD", "SELL", 1.3000, 1.2950, 1.3050)
    inverted, metadata = invert_signal(sig, True)

    audit.test(
        "Direction flipped SELL->BUY",
        inverted.side == "BUY",
        f"Got {inverted.side}"
    )

    # Test 1c: Reverse mode disabled
    print("\n[1c] With reverse_mode=False, signal should unchanged:")
    sig = create_signal("EURUSD", "BUY", 1.2000, 1.2100, 1.1950)
    inverted, metadata = invert_signal(sig, False)

    audit.test(
        "Direction unchanged when reverse_mode=False",
        inverted.side == "BUY",
        f"Got {inverted.side}"
    )

    audit.test(
        "was_inverted flag = False",
        metadata['was_inverted'] == False
    )

    return audit


def test_tp_sl_swap():
    """Test 2: TP/SL Swap Correctness"""
    print("\n" + "="*80)
    print("TEST 2: TP/SL SWAP")
    print("="*80)

    audit = InversionAudit()

    # Test 2a: TP and SL swap in BUY signal
    print("\n[2a] Original BUY: TP and SL should swap:")
    original_tp = 1.2100
    original_sl = 1.1950
    sig = create_signal("EURUSD", "BUY", 1.2000, original_tp, original_sl)
    inverted, metadata = invert_signal(sig, True)

    audit.test(
        "Original TP becomes SL",
        abs(inverted.sl - original_tp) < 0.00001,
        f"Original TP={original_tp}, Inverted SL={inverted.sl}"
    )

    audit.test(
        "Original SL becomes TP",
        abs(inverted.tp - original_sl) < 0.00001,
        f"Original SL={original_sl}, Inverted TP={inverted.tp}"
    )

    # Test 2b: TP and SL swap in SELL signal
    print("\n[2b] Original SELL: TP and SL should swap:")
    original_tp = 1.2950
    original_sl = 1.3050
    sig = create_signal("GBPUSD", "SELL", 1.3000, original_tp, original_sl)
    inverted, metadata = invert_signal(sig, True)

    audit.test(
        "Original TP becomes SL",
        abs(inverted.sl - original_tp) < 0.00001,
        f"Original TP={original_tp}, Inverted SL={inverted.sl}"
    )

    audit.test(
        "Original SL becomes TP",
        abs(inverted.tp - original_sl) < 0.00001,
        f"Original SL={original_sl}, Inverted TP={inverted.tp}"
    )

    return audit


def test_position_validation():
    """Test 3: TP/SL Position Validation (BUY: SL<E<TP, SELL: TP<E<SL)"""
    print("\n" + "="*80)
    print("TEST 3: TP/SL POSITION VALIDATION")
    print("="*80)

    audit = InversionAudit()

    # Test 3a: Valid BUY position
    print("\n[3a] Valid BUY: SL < entry < TP:")
    is_valid, reason = validate_inverted_levels("BUY", 1.2000, 1.2100, 1.1950)
    audit.test("BUY validation passes", is_valid, reason)

    # Test 3b: Invalid BUY position (TP below entry)
    print("\n[3b] Invalid BUY: TP below entry:")
    is_valid, reason = validate_inverted_levels("BUY", 1.2000, 1.1900, 1.1950)
    audit.test("BUY validation rejects (TP below entry)", not is_valid, reason)

    # Test 3c: Invalid BUY position (SL above entry)
    print("\n[3c] Invalid BUY: SL above entry:")
    is_valid, reason = validate_inverted_levels("BUY", 1.2000, 1.2100, 1.2050)
    audit.test("BUY validation rejects (SL above entry)", not is_valid, reason)

    # Test 3d: Valid SELL position
    print("\n[3d] Valid SELL: TP < entry < SL:")
    is_valid, reason = validate_inverted_levels("SELL", 1.3000, 1.2950, 1.3050)
    audit.test("SELL validation passes", is_valid, reason)

    # Test 3e: Invalid SELL position (TP above entry)
    print("\n[3e] Invalid SELL: TP above entry:")
    is_valid, reason = validate_inverted_levels("SELL", 1.3000, 1.3100, 1.3050)
    audit.test("SELL validation rejects (TP above entry)", not is_valid, reason)

    # Test 3f: Invalid SELL position (SL below entry)
    print("\n[3f] Invalid SELL: SL below entry:")
    is_valid, reason = validate_inverted_levels("SELL", 1.3000, 1.2950, 1.2900)
    audit.test("SELL validation rejects (SL below entry)", not is_valid, reason)

    return audit


def test_distance_consistency():
    """Test 4: Distance Consistency (entry to TP and SL distances mirror)"""
    print("\n" + "="*80)
    print("TEST 4: DISTANCE CONSISTENCY")
    print("="*80)

    audit = InversionAudit()

    # Test 4a: BUY distance preservation
    print("\n[4a] BUY: Distances should mirror after inversion:")
    entry = 1.2000
    original_tp = 1.2100  # +100 pips
    original_sl = 1.1950  # -50 pips

    sig = create_signal("EURUSD", "BUY", entry, original_tp, original_sl)
    inverted, _ = invert_signal(sig, True)

    # After inversion:
    # Original TP (1.2100) becomes SL
    # Original SL (1.1950) becomes TP
    # So: SELL @ 1.2000, TP=1.1950 (-50 pips), SL=1.2100 (+100 pips)

    original_tp_dist = original_tp - entry
    original_sl_dist = entry - original_sl

    inverted_tp_dist = entry - inverted.tp  # TP is now below entry for SELL
    inverted_sl_dist = inverted.sl - entry  # SL is now above entry for SELL

    audit.test(
        "TP distance preserved (mirrored)",
        abs(original_tp_dist - inverted_sl_dist) < 0.00001,
        f"Original TP dist={original_tp_dist:.5f}, Inverted SL dist={inverted_sl_dist:.5f}"
    )

    audit.test(
        "SL distance preserved (mirrored)",
        abs(original_sl_dist - inverted_tp_dist) < 0.00001,
        f"Original SL dist={original_sl_dist:.5f}, Inverted TP dist={inverted_tp_dist:.5f}"
    )

    # Test 4b: SELL distance preservation
    print("\n[4b] SELL: Distances should mirror after inversion:")
    entry = 1.3000
    original_tp = 1.2950  # -50 pips
    original_sl = 1.3050  # +50 pips

    sig = create_signal("GBPUSD", "SELL", entry, original_tp, original_sl)
    inverted, _ = invert_signal(sig, True)

    # After inversion:
    # Original TP (1.2950) becomes SL
    # Original SL (1.3050) becomes TP
    # So: BUY @ 1.3000, TP=1.3050 (+50 pips), SL=1.2950 (-50 pips)

    original_tp_dist = entry - original_tp
    original_sl_dist = original_sl - entry

    inverted_tp_dist = inverted.tp - entry  # TP is now above entry for BUY
    inverted_sl_dist = entry - inverted.sl  # SL is now below entry for BUY

    audit.test(
        "TP distance preserved (mirrored)",
        abs(original_tp_dist - inverted_sl_dist) < 0.00001,
        f"Original TP dist={original_tp_dist:.5f}, Inverted SL dist={inverted_sl_dist:.5f}"
    )

    audit.test(
        "SL distance preserved (mirrored)",
        abs(original_sl_dist - inverted_tp_dist) < 0.00001,
        f"Original SL dist={original_sl_dist:.5f}, Inverted TP dist={inverted_tp_dist:.5f}"
    )

    return audit


def test_edge_cases():
    """Test 5: Edge Cases"""
    print("\n" + "="*80)
    print("TEST 5: EDGE CASES")
    print("="*80)

    audit = InversionAudit()

    # Test 5a: Zero distance (should fail)
    print("\n[5a] Zero distance between entry and TP (should reject):")
    try:
        sig = create_signal("EURUSD", "BUY", 1.2000, 1.2000, 1.1950)
        inverted, _ = invert_signal(sig, True)
        audit.test("Should have raised ValueError", False, "No exception raised")
    except ValueError as e:
        audit.test("Correctly rejected zero-distance TP", True, str(e))

    # Test 5b: Very small distance (just under threshold)
    print("\n[5b] Very small distance (< 0.00001):")
    try:
        sig = create_signal("EURUSD", "BUY", 1.20000, 1.20000001, 1.1950)
        inverted, _ = invert_signal(sig, True)
        audit.test("Should have raised ValueError", False, "No exception raised")
    except ValueError as e:
        audit.test("Correctly rejected sub-threshold distance", True, str(e))

    # Test 5c: JPY pair with different scale (0.001 precision)
    print("\n[5c] JPY pair (0.001 precision):")
    sig = create_signal("EURIJPY", "BUY", 150.00, 151.00, 149.00)
    inverted, _ = invert_signal(sig, True)

    audit.test(
        "JPY pair inverted successfully",
        inverted.side == "SELL" and abs(inverted.tp - 149.00) < 0.001,
        f"Side={inverted.side}, TP={inverted.tp}"
    )

    # Test 5d: Very large distances
    print("\n[5d] Very large distances (100+ pips):")
    sig = create_signal("EURUSD", "BUY", 1.2000, 1.3000, 1.1000)
    inverted, _ = invert_signal(sig, True)

    audit.test(
        "Large distance trade inverted successfully",
        inverted.side == "SELL",
        f"Side={inverted.side}, TP dist={abs(inverted.tp - 1.2000)}"
    )

    return audit


def test_entry_price_stability():
    """Test 6: Entry Price Must Never Change"""
    print("\n" + "="*80)
    print("TEST 6: ENTRY PRICE STABILITY")
    print("="*80)

    audit = InversionAudit()

    entry_prices = [1.0001, 1.2000, 1.5555, 100.0000, 0.9999]

    for entry in entry_prices:
        tp = entry + 0.0100
        sl = entry - 0.0050

        sig = create_signal("EURUSD", "BUY", entry, tp, sl)
        inverted, _ = invert_signal(sig, True)

        audit.test(
            f"Entry price preserved ({entry})",
            abs(inverted.open_price - entry) < 0.00001,
            f"Expected {entry}, got {inverted.open_price}"
        )

    return audit


def test_integration_isolation():
    """Test 7: Integration Isolation (inversion only in execution layer)"""
    print("\n" + "="*80)
    print("TEST 7: INTEGRATION ISOLATION")
    print("="*80)

    audit = InversionAudit()

    # Test that original signal is never modified
    print("\n[7a] Original signal should remain unchanged after inversion:")
    sig = create_signal("EURUSD", "BUY", 1.2000, 1.2100, 1.1950)
    original_side = sig.side
    original_tp = sig.tp
    original_sl = sig.sl

    inverted, metadata = invert_signal(sig, True)

    audit.test(
        "Original signal side unchanged",
        sig.side == original_side,
        f"Side changed from {original_side} to {sig.side}"
    )

    audit.test(
        "Original signal TP unchanged",
        abs(sig.tp - original_tp) < 0.00001,
        f"TP changed from {original_tp} to {sig.tp}"
    )

    audit.test(
        "Original signal SL unchanged",
        abs(sig.sl - original_sl) < 0.00001,
        f"SL changed from {original_sl} to {sig.sl}"
    )

    # Test that metadata is correct
    print("\n[7b] Metadata should accurately reflect inversion:")
    audit.test(
        "was_inverted flag set correctly",
        metadata['was_inverted'] == True
    )

    audit.test(
        "original_side recorded correctly",
        metadata['original_side'] == "BUY"
    )

    return audit


def test_metadata_logging():
    """Test 8: Metadata and Logging"""
    print("\n" + "="*80)
    print("TEST 8: METADATA & LOGGING")
    print("="*80)

    audit = InversionAudit()

    sig = create_signal("EURUSD", "BUY", 1.2000, 1.2100, 1.1950)
    inverted, metadata = invert_signal(sig, True)

    audit.test(
        "Metadata contains was_inverted",
        'was_inverted' in metadata,
        f"Keys: {list(metadata.keys())}"
    )

    audit.test(
        "Metadata contains original_side",
        'original_side' in metadata and metadata['original_side'] == "BUY"
    )

    audit.test(
        "Metadata contains original_tp",
        'original_tp' in metadata and abs(metadata['original_tp'] - 1.2100) < 0.00001
    )

    audit.test(
        "Metadata contains original_sl",
        'original_sl' in metadata and abs(metadata['original_sl'] - 1.1950) < 0.00001
    )

    audit.test(
        "Metadata contains validation_result",
        'validation_result' in metadata and isinstance(metadata['validation_result'], tuple)
    )

    return audit


# ══════════════════════════════════════════════════════════════════════════════
# MAIN AUDIT
# ══════════════════════════════════════════════════════════════════════════════

def run_full_audit():
    """Run complete audit suite."""
    print("\n" + "="*80)
    print("  SIGNAL INVERSION AUDIT - COMPREHENSIVE VERIFICATION".center(80))
    print("="*80)

    all_audits = [
        test_direction_inversion(),
        test_tp_sl_swap(),
        test_position_validation(),
        test_distance_consistency(),
        test_edge_cases(),
        test_entry_price_stability(),
        test_integration_isolation(),
        test_metadata_logging(),
    ]

    total_passed = sum(a.passed for a in all_audits)
    total_failed = sum(a.failed for a in all_audits)
    total = total_passed + total_failed

    print("\n" + "="*80)
    print(f"  FINAL RESULTS: {total_passed}/{total} tests passed".center(80))
    if total_failed > 0:
        print(f"  WARNING: {total_failed} test(s) FAILED".center(80))
    else:
        print(f"  SUCCESS: ALL TESTS PASSED".center(80))
    print("="*80 + "\n")

    return total_failed == 0


if __name__ == "__main__":
    success = run_full_audit()
    exit(0 if success else 1)
