import os
import pandas as pd

files = [
    "dlf_superflex.csv",
    "dlf_idp.csv",
    "dlf_rookie_superflex.csv",
    "dlf_rookie_idp.csv",
]

for fname in files:
    print("\n" + "=" * 80)
    print(fname)
    print("=" * 80)

    if not os.path.exists(fname):
        print("MISSING")
        continue

    try:
        df = pd.read_csv(fname)
        print("Rows:", len(df))
        print("Columns:", list(df.columns))
        print(df.head(5).to_string(index=False))
    except Exception as e:
        print("FAILED TO READ:", e)