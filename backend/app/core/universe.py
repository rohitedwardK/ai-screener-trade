"""Nifty 50 universe of stocks (yfinance ".NS" suffix).

The Nifty 50 is rebalanced semi-annually by NSE Indices. Update this list
periodically using the official factsheet at niftyindices.com.
"""
from __future__ import annotations

from typing import List, Tuple

# (symbol_with_NS_suffix, display_name, sector)
NIFTY_50: List[Tuple[str, str, str]] = [
    ("RELIANCE.NS", "Reliance Industries Ltd.", "Energy"),
    ("TCS.NS", "Tata Consultancy Services Ltd.", "IT"),
    ("HDFCBANK.NS", "HDFC Bank Ltd.", "Financial Services"),
    ("INFY.NS", "Infosys Ltd.", "IT"),
    ("ICICIBANK.NS", "ICICI Bank Ltd.", "Financial Services"),
    ("HINDUNILVR.NS", "Hindustan Unilever Ltd.", "FMCG"),
    ("ITC.NS", "ITC Ltd.", "FMCG"),
    ("SBIN.NS", "State Bank of India", "Financial Services"),
    ("BHARTIARTL.NS", "Bharti Airtel Ltd.", "Telecom"),
    ("LT.NS", "Larsen & Toubro Ltd.", "Construction"),
    ("KOTAKBANK.NS", "Kotak Mahindra Bank Ltd.", "Financial Services"),
    ("AXISBANK.NS", "Axis Bank Ltd.", "Financial Services"),
    ("MARUTI.NS", "Maruti Suzuki India Ltd.", "Auto"),
    ("ASIANPAINT.NS", "Asian Paints Ltd.", "Consumer Durables"),
    ("HCLTECH.NS", "HCL Technologies Ltd.", "IT"),
    ("BAJFINANCE.NS", "Bajaj Finance Ltd.", "Financial Services"),
    ("SUNPHARMA.NS", "Sun Pharmaceutical Industries Ltd.", "Pharma"),
    ("TITAN.NS", "Titan Company Ltd.", "Consumer Durables"),
    ("M&M.NS", "Mahindra & Mahindra Ltd.", "Auto"),
    ("ULTRACEMCO.NS", "UltraTech Cement Ltd.", "Cement"),
    ("NTPC.NS", "NTPC Ltd.", "Power"),
    ("NESTLEIND.NS", "Nestle India Ltd.", "FMCG"),
    ("POWERGRID.NS", "Power Grid Corporation of India Ltd.", "Power"),
    ("TMPV.NS", "Tata Motors Passenger Vehicles Ltd.", "Auto"),
    ("WIPRO.NS", "Wipro Ltd.", "IT"),
    ("BAJAJFINSV.NS", "Bajaj Finserv Ltd.", "Financial Services"),
    ("ONGC.NS", "Oil and Natural Gas Corporation Ltd.", "Energy"),
    ("ADANIENT.NS", "Adani Enterprises Ltd.", "Metals & Mining"),
    ("JSWSTEEL.NS", "JSW Steel Ltd.", "Metals & Mining"),
    ("COALINDIA.NS", "Coal India Ltd.", "Metals & Mining"),
    ("TATASTEEL.NS", "Tata Steel Ltd.", "Metals & Mining"),
    ("HINDALCO.NS", "Hindalco Industries Ltd.", "Metals & Mining"),
    ("GRASIM.NS", "Grasim Industries Ltd.", "Cement"),
    ("ADANIPORTS.NS", "Adani Ports and Special Economic Zone Ltd.", "Services"),
    ("BAJAJ-AUTO.NS", "Bajaj Auto Ltd.", "Auto"),
    ("INDUSINDBK.NS", "IndusInd Bank Ltd.", "Financial Services"),
    ("DRREDDY.NS", "Dr. Reddy's Laboratories Ltd.", "Pharma"),
    ("EICHERMOT.NS", "Eicher Motors Ltd.", "Auto"),
    ("CIPLA.NS", "Cipla Ltd.", "Pharma"),
    ("BRITANNIA.NS", "Britannia Industries Ltd.", "FMCG"),
    ("HEROMOTOCO.NS", "Hero MotoCorp Ltd.", "Auto"),
    ("APOLLOHOSP.NS", "Apollo Hospitals Enterprise Ltd.", "Healthcare"),
    ("DIVISLAB.NS", "Divi's Laboratories Ltd.", "Pharma"),
    ("TECHM.NS", "Tech Mahindra Ltd.", "IT"),
    ("TATACONSUM.NS", "Tata Consumer Products Ltd.", "FMCG"),
    ("SBILIFE.NS", "SBI Life Insurance Company Ltd.", "Financial Services"),
    ("HDFCLIFE.NS", "HDFC Life Insurance Company Ltd.", "Financial Services"),
    ("PNB.NS", "Punjab National Bank", "Financial Services"),
    ("BPCL.NS", "Bharat Petroleum Corporation Ltd.", "Energy"),
    ("LTM.NS", "LTM Ltd.", "IT"),
    ("SHRIRAMFIN.NS", "Shriram Finance Ltd.", "Financial Services"),
]


def all_symbols() -> List[str]:
    return [s for s, _, _ in NIFTY_50]


def stock_meta() -> List[dict]:
    return [{"symbol": s, "name": n, "sector": sec} for s, n, sec in NIFTY_50]
