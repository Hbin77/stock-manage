"""
모니터링 종목 리스트 모듈
NASDAQ 100 + S&P 500 구성 종목 정의

사용법:
    from config.tickers import ALL_TICKERS, NASDAQ_100, SP500, TICKER_INDEX
"""

# ─────────────────────────────────────────────────────────────────────────────
# NASDAQ 100 구성 종목 (2025년 기준, ~101개)
# ─────────────────────────────────────────────────────────────────────────────
NASDAQ_100: list[str] = [
    "AAPL",  # Apple
    "MSFT",  # Microsoft
    "NVDA",  # NVIDIA
    "AMZN",  # Amazon
    "META",  # Meta Platforms
    "GOOGL", # Alphabet Class A
    "GOOG",  # Alphabet Class C
    "TSLA",  # Tesla
    "AVGO",  # Broadcom
    "COST",  # Costco
    "NFLX",  # Netflix
    "AMD",   # Advanced Micro Devices
    "TMUS",  # T-Mobile
    "ADBE",  # Adobe
    "CSCO",  # Cisco
    "QCOM",  # Qualcomm
    "INTU",  # Intuit
    "TXN",   # Texas Instruments
    "AMAT",  # Applied Materials
    "AMGN",  # Amgen
    "BKNG",  # Booking Holdings
    "ISRG",  # Intuitive Surgical
    "MU",    # Micron Technology
    "LRCX",  # Lam Research
    "HON",   # Honeywell
    "REGN",  # Regeneron
    "PANW",  # Palo Alto Networks
    "VRTX",  # Vertex Pharmaceuticals
    "KLAC",  # KLA Corp
    "ADI",   # Analog Devices
    "GILD",  # Gilead Sciences
    "MELI",  # MercadoLibre
    "ASML",  # ASML Holding
    "MDLZ",  # Mondelez
    "SBUX",  # Starbucks
    "ABNB",  # Airbnb
    "CDNS",  # Cadence Design
    "SNPS",  # Synopsys
    "CSX",   # CSX Corp
    "CTAS",  # Cintas
    "PDD",   # PDD Holdings
    "CEG",   # Constellation Energy
    "MCHP",  # Microchip Technology
    "FTNT",  # Fortinet
    "NXPI",  # NXP Semiconductors
    "ORLY",  # O'Reilly Auto Parts
    "PAYX",  # Paychex
    "ADP",   # Automatic Data Processing
    "WDAY",  # Workday
    "PYPL",  # PayPal
    "TEAM",  # Atlassian
    "DXCM",  # DexCom
    "BIIB",  # Biogen
    "IDXX",  # IDEXX Laboratories
    "MRNA",  # Moderna
    "ZS",    # Zscaler
    "ALGN",  # Align Technology
    "FANG",  # Diamondback Energy
    "FAST",  # Fastenal
    "PCAR",  # PACCAR
    "KDP",   # Keurig Dr Pepper
    "CPRT",  # Copart
    "VRSK",  # Verisk Analytics
    "MNST",  # Monster Beverage
    "AEP",   # American Electric Power
    "XEL",   # Xcel Energy
    "EXC",   # Exelon
    "ANSS",  # ANSYS
    "ODFL",  # Old Dominion Freight
    "DLTR",  # Dollar Tree
    "CRWD",  # CrowdStrike
    "DDOG",  # Datadog
    "ROST",  # Ross Stores
    "EA",    # Electronic Arts
    "EBAY",  # eBay
    "KHC",   # Kraft Heinz
    "CMCSA", # Comcast
    "CHTR",  # Charter Communications
    "VRSN",  # VeriSign
    "FISV",  # Fiserv
    "TTD",   # The Trade Desk
    "ON",    # ON Semiconductor
    "GEHC",  # GE HealthCare
    "MRVL",  # Marvell Technology
    "INTC",  # Intel
    "ILMN",  # Illumina
    "ZM",    # Zoom Video
    "WBA",   # Walgreens
    "SIRI",  # Sirius XM
    "ROP",   # Roper Technologies
    "TTWO",  # Take-Two Interactive
    "OKTA",  # Okta
    "GFS",   # GlobalFoundries
    "LCID",  # Lucid Group
    "RIVN",  # Rivian
    "ARM",   # ARM Holdings
    "SMCI",  # Super Micro Computer
    "APP",   # Applovin
    "COIN",  # Coinbase
    "PLTR",  # Palantir
]

# ─────────────────────────────────────────────────────────────────────────────
# S&P 500 구성 종목 (2025년 기준, ~503개)
# ─────────────────────────────────────────────────────────────────────────────
SP500: list[str] = [
    # Technology
    "AAPL", "MSFT", "NVDA", "AVGO", "ORCL", "CRM", "ACN", "IBM", "INTC",
    "QCOM", "TXN", "AMAT", "ADI", "LRCX", "MU", "KLAC", "MCHP", "NXPI",
    "ON", "SNPS", "CDNS", "FTNT", "PANW", "CRWD", "CTSH", "IT", "CDW",
    "STX", "WDC", "NTAP", "HPQ", "HPE", "JNPR", "GLW", "FFIV", "VRSN",
    "ANSS", "PTC", "EPAM", "GDDY", "LDOS", "SAIC", "AKAM", "VRT",
    # Communication Services
    "GOOGL", "GOOG", "META", "NFLX", "CMCSA", "TMUS", "VZ", "T", "CHTR",
    "TTWO", "EA", "WBD", "FOXA", "FOX", "PARA", "IPG", "OMC", "MTCH",
    "LUMN", "NWSA", "NWS",
    # Consumer Discretionary
    "AMZN", "TSLA", "HD", "MCD", "NKE", "SBUX", "LOW", "TJX", "BKNG",
    "CMG", "ORLY", "AZO", "ROST", "DHI", "LEN", "PHM", "NVR", "TOL",
    "TSCO", "EBAY", "APTV", "GM", "F", "LVS", "WYNN", "MGM", "CCL",
    "RCL", "NCLH", "MAR", "HLT", "YUM", "DPZ", "DRI", "ABNB", "EXPE",
    "TRIP", "LKQ", "KMX", "AN", "PAG", "GPC", "BBY", "ULTA", "TPR",
    "TGT", "RVTY", "PVH", "HAS", "MHK", "POOL", "DECK", "VFC",
    # Consumer Staples
    "WMT", "COST", "PG", "KO", "PEP", "PM", "MO", "MDLZ", "KHC",
    "GIS", "K", "CPB", "CAG", "SJM", "HRL", "MKC", "CLX", "CL",
    "KMB", "CHD", "EL", "KDP", "MNST", "STZ", "BF.B", "TAP", "KVUE",
    "HSY", "TSN", "SFM",
    # Energy
    "XOM", "CVX", "COP", "EOG", "SLB", "MPC", "PSX", "VLO", "OXY",
    "PXD", "FANG", "DVN", "HAL", "BKR", "HES", "APA", "TRGP", "KMI",
    "OKE", "WMB", "LNG", "CTRA", "MRO", "EQT", "CEG", "NRG", "VST",
    # Financials
    "BRK.B", "JPM", "BAC", "WFC", "GS", "MS", "C", "BX", "AXP",
    "SCHW", "BLK", "SPGI", "MCO", "ICE", "CME", "NDAQ", "CB", "AIG",
    "MET", "PRU", "AFL", "ALL", "PGR", "TRV", "HIG", "LNC", "L",
    "MTB", "USB", "PNC", "TFC", "KEY", "HBAN", "RF", "CFG", "FITB",
    "STT", "BK", "NTRS", "AMP", "LM", "TROW", "IVZ", "BEN", "ACGL",
    "RJF", "EG", "MKL", "CINF", "WRB", "AIZ", "CPAY", "FI", "FIS",
    "FISV", "MA", "V", "PYPL", "SYF", "DFS", "COF", "ADS", "ALLY",
    # Health Care
    "LLY", "UNH", "JNJ", "ABBV", "MRK", "ABT", "BMY", "AMGN", "GILD",
    "ISRG", "VRTX", "REGN", "BIIB", "MRNA", "ILMN", "IDXX", "ALGN",
    "DXCM", "ZBH", "EW", "BSX", "MDT", "SYK", "BDX", "BAX", "RMD",
    "HOLX", "DGX", "LH", "PKI", "INCY", "SGEN", "PODD", "TECH",
    "MCK", "CVS", "CI", "HUM", "CNC", "MOH", "ELV", "UHS", "HCA",
    "THC", "HSIC", "PDCO", "CAH", "ABC", "COR", "IQV", "A", "TMO",
    "DHR", "WAT", "MTD", "KEYS", "MKTX",
    # Industrials
    "HON", "RTX", "CAT", "DE", "LMT", "NOC", "GD", "BA", "EMR",
    "GE", "ETN", "PH", "ROK", "DOV", "IR", "AOS", "MAS", "ALLE",
    "OTIS", "CARR", "TT", "JCI", "CTAS", "FAST", "GWW", "MSI", "SNA",
    "PCAR", "CMI", "TEL", "AMP", "LHX", "HII", "DRS", "LDOS", "SAIC",
    "AXON", "TDG", "TDY", "TER", "TRMB", "FTV", "NVT", "HUBB",
    "AME", "ROP", "XYL", "XYLD", "ITW", "CHRW", "EXPD", "JBHT",
    "NSC", "UNP", "CSX", "DAL", "UAL", "AAL", "LUV", "ALK", "SAVE",
    "FDX", "UPS", "ODFL", "SAIA", "WERN", "KNX", "ABM", "ADP",
    "PAYX", "CDAY", "PAYC", "BR", "VRSK", "CPRT", "RSG", "WM", "CLH",
    # Materials
    "LIN", "APD", "SHW", "ECL", "DD", "DOW", "LYB", "NUE", "STLD",
    "CF", "MOS", "ALB", "FCX", "NEM", "GOLD", "AEM", "FNV", "WPM",
    "BALL", "AMCR", "IP", "PKG", "WRK", "SEE", "AVY", "IFF", "PPG",
    "RPM", "VMC", "MLM", "CE", "EMN", "FMC", "WLK", "ASH",
    # Real Estate
    "AMT", "PLD", "CCI", "EQIX", "PSA", "WELL", "SPG", "O", "VICI",
    "EQR", "AVB", "ESS", "MAA", "UDR", "CPT", "ARE", "BXP", "VTR",
    "PEAK", "HR", "DOC", "SBAC", "SBA", "AMH", "INVH", "EXR", "LSI",
    "CSGP", "CBRE", "JLL", "CWK", "RKT", "MTG", "REXR", "FR", "EGP",
    "COLD", "STAG", "WPC", "REG", "KIM", "FRT", "BRX", "RPAI",
    # Utilities
    "NEE", "DUK", "SO", "D", "AEP", "EXC", "SRE", "XEL", "ED",
    "EIX", "ETR", "ES", "AEE", "LNT", "EVRG", "WEC", "DTE", "NI",
    "PNW", "NRG", "CEG", "PCG", "PEG", "AWK", "WTR", "SWX", "SJW",
    "ATO", "CMS", "CNP", "OGE", "UGI", "GAS", "NW", "SR",
]

# 중복 제거 후 정렬된 전체 종목 리스트
ALL_TICKERS: list[str] = sorted(set(NASDAQ_100 + SP500))

# 각 티커가 속한 인덱스 정보
# {ticker: ["NASDAQ100", "SP500"]} 형태
TICKER_INDEX: dict[str, list[str]] = {}
for _t in ALL_TICKERS:
    _indices = []
    if _t in NASDAQ_100:
        _indices.append("NASDAQ100")
    if _t in SP500:
        _indices.append("SP500")
    TICKER_INDEX[_t] = _indices


def get_tickers_by_index(index_name: str) -> list[str]:
    """특정 인덱스 소속 티커 리스트 반환"""
    if index_name == "NASDAQ100":
        return sorted(set(NASDAQ_100))
    elif index_name == "SP500":
        return sorted(set(SP500))
    return ALL_TICKERS


if __name__ == "__main__":
    print(f"NASDAQ 100: {len(set(NASDAQ_100))}개")
    print(f"S&P 500: {len(set(SP500))}개")
    print(f"전체 (중복 제거): {len(ALL_TICKERS)}개")
    overlap = set(NASDAQ_100) & set(SP500)
    print(f"중복 (양쪽 포함): {len(overlap)}개")
