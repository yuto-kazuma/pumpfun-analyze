import hashlib

names = [
    "buy",
    "sell",
    "buy_v2",
    "sell_v2",
    "buy_exact_sol_in",
    "extend_account",
    "set_creator",
    "collect_creator_fee",
    "toggle_mayhem_mode",
    "create_v2",
    "migrate",
    "withdraw",
    "initialize",
    "buy_exact_sol_in",
]
wanted = {
    "07051dc4f5176550",
    "e1f7501ed5b38488",
    "e445a52e51cb9a1d",
    "e84b2c916a0f33d7",
    "1d5a9e43c70b86f2",
    "e19a7516d756f667",
}
for n in names:
    d = hashlib.sha256(f"global:{n}".encode()).digest()[:8].hex()
    mark = " <<<" if d in wanted else ""
    print(n, d, mark)

# brute common suffixes
for n in [
    "buy_exact_sol_in",
    "sell_exact_sol_in",
    "claim_token_incentives",
    "admin_set_creator",
    "set_metaplex_creator",
    "update_global",
    "create",
]:
    d = hashlib.sha256(f"global:{n}".encode()).digest()[:8].hex()
    print("extra", n, d, "<<<" if d in wanted else "")

print("anchor event ix", hashlib.sha256(b"anchor:event").digest()[:8].hex())
