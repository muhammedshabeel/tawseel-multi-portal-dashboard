import pandas as pd

from src.metrics import add_derived_columns, classify_status


def test_classify_status():
    assert classify_status("Delivered") == "Delivered"
    assert classify_status("Out for Delivery") == "Out for Delivery"
    assert classify_status("RTO") == "RTO"


def test_add_derived_columns():
    df = pd.DataFrame({"Status": ["Delivered", "RTO"], "Priority": ["DONE", "CRITICAL - CALL NOW"]})
    out = add_derived_columns(df)
    assert out["Is Delivered"].tolist() == [True, False]
    assert out["Is Critical"].tolist() == [False, True]
