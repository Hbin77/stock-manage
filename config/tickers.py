"""
모니터링 종목 리스트 모듈
NASDAQ 100 + S&P 500 + 주요 ETF + MidCap + SmallCap 성장주

사용법:
    from config.tickers import (
        ALL_TICKERS, NASDAQ_100, SP500,
        POPULAR_ETFS, MID_CAP, SMALL_CAP_GROWTH,
        TICKER_INDEX, get_tickers_by_index,
    )
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

# ─────────────────────────────────────────────────────────────────────────────
# 주요 ETF — 거래량/자산 규모 기준 인기 ETF (yfinance 조회 가능 확인)
# ─────────────────────────────────────────────────────────────────────────────
POPULAR_ETFS: list[str] = [
    # ── 시장 전체 / 대형 인덱스 ──────────────────────────────────────────────
    "SPY",   # SPDR S&P 500 ETF
    "QQQ",   # Invesco NASDAQ 100 ETF
    "DIA",   # SPDR Dow Jones Industrial Average ETF
    "IWM",   # iShares Russell 2000 ETF
    "VTI",   # Vanguard Total Stock Market ETF
    "VOO",   # Vanguard S&P 500 ETF
    "IVV",   # iShares Core S&P 500 ETF
    "RSP",   # Invesco S&P 500 Equal Weight ETF
    "MDY",   # SPDR S&P MidCap 400 ETF
    "IJH",   # iShares Core S&P MidCap 400 ETF
    "IJR",   # iShares Core S&P SmallCap 600 ETF
    "IWF",   # iShares Russell 1000 Growth ETF
    "IWD",   # iShares Russell 1000 Value ETF
    "IWO",   # iShares Russell 2000 Growth ETF
    "IWN",   # iShares Russell 2000 Value ETF
    "VTV",   # Vanguard Value ETF
    "VUG",   # Vanguard Growth ETF
    "VXUS",  # Vanguard Total International Stock ETF
    "SCHX",  # Schwab U.S. Large-Cap ETF
    "SPLG",  # SPDR Portfolio S&P 500 ETF

    # ── 섹터 ETF (Select Sector SPDRs + 기타) ────────────────────────────────
    "XLK",   # Technology Select Sector SPDR
    "XLF",   # Financial Select Sector SPDR
    "XLE",   # Energy Select Sector SPDR
    "XLV",   # Health Care Select Sector SPDR
    "XLI",   # Industrial Select Sector SPDR
    "XLC",   # Communication Services Select Sector SPDR
    "XLY",   # Consumer Discretionary Select Sector SPDR
    "XLP",   # Consumer Staples Select Sector SPDR
    "XLB",   # Materials Select Sector SPDR
    "XLU",   # Utilities Select Sector SPDR
    "XLRE",  # Real Estate Select Sector SPDR
    "VGT",   # Vanguard Information Technology ETF
    "VHT",   # Vanguard Health Care ETF
    "VFH",   # Vanguard Financials ETF
    "VDE",   # Vanguard Energy ETF
    "VNQ",   # Vanguard Real Estate ETF
    "VIS",   # Vanguard Industrials ETF
    "VAW",   # Vanguard Materials ETF
    "VCR",   # Vanguard Consumer Discretionary ETF
    "VDC",   # Vanguard Consumer Staples ETF
    "VOX",   # Vanguard Communication Services ETF

    # ── 테마 / 혁신 ETF ──────────────────────────────────────────────────────
    "ARKK",  # ARK Innovation ETF
    "ARKW",  # ARK Next Generation Internet ETF
    "ARKG",  # ARK Genomic Revolution ETF
    "ARKF",  # ARK Fintech Innovation ETF
    "SOXX",  # iShares Semiconductor ETF
    "SMH",   # VanEck Semiconductor ETF
    "HACK",  # ETFMG Prime Cyber Security ETF
    "BOTZ",  # Global X Robotics & AI ETF
    "ROBO",  # Robo Global Robotics & Automation ETF
    "LIT",   # Global X Lithium & Battery Tech ETF
    "TAN",   # Invesco Solar ETF
    "ICLN",  # iShares Global Clean Energy ETF
    "QCLN",  # First Trust NASDAQ Clean Edge Green Energy ETF
    "XBI",   # SPDR S&P Biotech ETF
    "IBB",   # iShares Biotechnology ETF
    "KWEB",  # KraneShares CSI China Internet ETF
    "MCHI",  # iShares MSCI China ETF
    "IGV",   # iShares Expanded Tech-Software Sector ETF
    "SKYY",  # First Trust Cloud Computing ETF
    "WCLD",  # WisdomTree Cloud Computing ETF
    "CIBR",  # First Trust NASDAQ Cybersecurity ETF
    "XHB",   # SPDR S&P Homebuilders ETF
    "XRT",   # SPDR S&P Retail ETF
    "XOP",   # SPDR S&P Oil & Gas Exploration & Production ETF
    "XME",   # SPDR S&P Metals & Mining ETF
    "KRE",   # SPDR S&P Regional Banking ETF
    "KBE",   # SPDR S&P Bank ETF
    "ITA",   # iShares U.S. Aerospace & Defense ETF
    "JETS",  # U.S. Global Jets ETF
    "PBW",   # Invesco WilderHill Clean Energy ETF
    "DRIV",  # Global X Autonomous & Electric Vehicles ETF

    # ── 채권 ETF ─────────────────────────────────────────────────────────────
    "TLT",   # iShares 20+ Year Treasury Bond ETF
    "IEF",   # iShares 7-10 Year Treasury Bond ETF
    "SHY",   # iShares 1-3 Year Treasury Bond ETF
    "AGG",   # iShares Core U.S. Aggregate Bond ETF
    "BND",   # Vanguard Total Bond Market ETF
    "HYG",   # iShares iBoxx High Yield Corporate Bond ETF
    "LQD",   # iShares iBoxx Investment Grade Corporate Bond ETF
    "TIP",   # iShares TIPS Bond ETF
    "TIPS",  # SPDR Bloomberg TIPS ETF (iShares)
    "SHV",   # iShares Short Treasury Bond ETF
    "BNDX",  # Vanguard Total International Bond ETF
    "EMB",   # iShares J.P. Morgan USD Emerging Markets Bond ETF
    "MUB",   # iShares National Muni Bond ETF
    "VCIT",  # Vanguard Intermediate-Term Corporate Bond ETF
    "VCSH",  # Vanguard Short-Term Corporate Bond ETF
    "GOVT",  # iShares U.S. Treasury Bond ETF
    "TMF",   # Direxion Daily 20+ Year Treasury Bull 3X Shares
    "TMV",   # Direxion Daily 20+ Year Treasury Bear 3X Shares

    # ── 원자재 / 실물자산 ETF ────────────────────────────────────────────────
    "GLD",   # SPDR Gold Shares
    "SLV",   # iShares Silver Trust
    "IAU",   # iShares Gold Trust
    "USO",   # United States Oil Fund
    "UNG",   # United States Natural Gas Fund
    "DBA",   # Invesco DB Agriculture Fund
    "PDBC",  # Invesco Optimum Yield Diversified Commodity Strategy No K-1 ETF
    "DBC",   # Invesco DB Commodity Index Tracking Fund
    "WEAT",  # Teucrium Wheat Fund
    "CORN",  # Teucrium Corn Fund
    "PPLT",  # abrdn Physical Platinum Shares ETF
    "PALL",  # abrdn Physical Palladium Shares ETF
    "COPX",  # Global X Copper Miners ETF

    # ── 레버리지 / 인버스 ETF ────────────────────────────────────────────────
    "TQQQ",  # ProShares UltraPro QQQ (3x NASDAQ 100)
    "SQQQ",  # ProShares UltraPro Short QQQ (-3x NASDAQ 100)
    "SPXU",  # ProShares UltraPro Short S&P 500 (-3x)
    "UPRO",  # ProShares UltraPro S&P 500 (3x)
    "LABU",  # Direxion Daily S&P Biotech Bull 3X Shares
    "LABD",  # Direxion Daily S&P Biotech Bear 3X Shares
    "SOXL",  # Direxion Daily Semiconductor Bull 3X Shares
    "SOXS",  # Direxion Daily Semiconductor Bear 3X Shares
    "SPXS",  # Direxion Daily S&P 500 Bear 3X Shares
    "TNA",   # Direxion Daily Small Cap Bull 3X Shares
    "TZA",   # Direxion Daily Small Cap Bear 3X Shares
    "UVXY",  # ProShares Ultra VIX Short-Term Futures ETF
    "SVXY",  # ProShares Short VIX Short-Term Futures ETF
    "SSO",   # ProShares Ultra S&P 500 (2x)
    "SDS",   # ProShares UltraShort S&P 500 (-2x)
    "QLD",   # ProShares Ultra QQQ (2x)
    "QID",   # ProShares UltraShort QQQ (-2x)
    "FNGU",  # MicroSectors FANG+ Index 3X Leveraged ETN
    "FNGD",  # MicroSectors FANG+ Index -3X Inverse Leveraged ETN

    # ── 해외 / 글로벌 ETF ────────────────────────────────────────────────────
    "EEM",   # iShares MSCI Emerging Markets ETF
    "EFA",   # iShares MSCI EAFE ETF
    "VWO",   # Vanguard FTSE Emerging Markets ETF
    "FXI",   # iShares China Large-Cap ETF
    "INDA",  # iShares MSCI India ETF
    "EWJ",   # iShares MSCI Japan ETF
    "EWZ",   # iShares MSCI Brazil ETF
    "EWY",   # iShares MSCI South Korea ETF
    "EWT",   # iShares MSCI Taiwan ETF
    "EWG",   # iShares MSCI Germany ETF
    "EWU",   # iShares MSCI United Kingdom ETF
    "EWA",   # iShares MSCI Australia ETF
    "EWC",   # iShares MSCI Canada ETF
    "VEA",   # Vanguard FTSE Developed Markets ETF
    "IEMG",  # iShares Core MSCI Emerging Markets ETF
    "ACWI",  # iShares MSCI ACWI ETF

    # ── 배당 / 인컴 ETF ─────────────────────────────────────────────────────
    "VIG",   # Vanguard Dividend Appreciation ETF
    "SCHD",  # Schwab U.S. Dividend Equity ETF
    "DVY",   # iShares Select Dividend ETF
    "HDV",   # iShares Core High Dividend ETF
    "JEPI",  # JPMorgan Equity Premium Income ETF
    "JEPQ",  # JPMorgan Nasdaq Equity Premium Income ETF
    "NOBL",  # ProShares S&P 500 Dividend Aristocrats ETF
    "VYM",   # Vanguard High Dividend Yield ETF
    "DGRO",  # iShares Core Dividend Growth ETF
    "SPYD",  # SPDR Portfolio S&P 500 High Dividend ETF
    "DIVO",  # Amplify CWP Enhanced Dividend Income ETF
    "QYLD",  # Global X NASDAQ 100 Covered Call ETF
    "XYLD",  # Global X S&P 500 Covered Call ETF
    "NUSI",  # Nationwide Nasdaq-100 Risk-Managed Income ETF

    # ── 크립토 관련 ETF ──────────────────────────────────────────────────────
    "IBIT",  # iShares Bitcoin Trust ETF
    "ETHE",  # Grayscale Ethereum Trust
    "GBTC",  # Grayscale Bitcoin Trust
    "BITO",  # ProShares Bitcoin Strategy ETF
    "FBTC",  # Fidelity Wise Origin Bitcoin Fund

    # ── 변동성 / 전략 ETF ────────────────────────────────────────────────────
    "VIXY",  # ProShares VIX Short-Term Futures ETF
    "SPLV",  # Invesco S&P 500 Low Volatility ETF
    "USMV",  # iShares MSCI USA Minimum Volatility ETF
    "MTUM",  # iShares MSCI USA Momentum Factor ETF
    "QUAL",  # iShares MSCI USA Quality Factor ETF
    "VLUE",  # iShares MSCI USA Value Factor ETF
    "SIZE",  # iShares MSCI USA Size Factor ETF
]

# ─────────────────────────────────────────────────────────────────────────────
# S&P 400 MidCap 주요 종목 — 시가총액 상위 100개 (2025년 기준)
# ─────────────────────────────────────────────────────────────────────────────
MID_CAP: list[str] = [
    "DECK",  # Deckers Outdoor
    "WSM",   # Williams-Sonoma
    "FNF",   # Fidelity National Financial
    "SAIA",  # Saia Inc (물류)
    "BURL",  # Burlington Stores
    "TOST",  # Toast Inc (핀테크)
    "DUOL",  # Duolingo (에드테크)
    "RKLB",  # Rocket Lab USA (우주)
    "HOOD",  # Robinhood Markets
    "SOFI",  # SoFi Technologies
    "RBC",   # RBC Bearings
    "MANH",  # Manhattan Associates
    "LSCC",  # Lattice Semiconductor
    "WFRD",  # Weatherford International
    "ELF",   # e.l.f. Beauty
    "ATI",   # ATI Inc (특수 금속)
    "SKX",   # Skechers USA
    "WING",  # Wingstop
    "CACI",  # CACI International
    "EWBC",  # East West Bancorp
    "EXLS",  # ExlService Holdings
    "PNFP",  # Pinnacle Financial Partners
    "PCOR",  # Procore Technologies
    "JBL",   # Jabil Inc
    "TNET",  # TriNet Group
    "MKSI",  # MKS Instruments
    "NOVT",  # Novanta Inc
    "AZEK",  # AZEK Company
    "FIX",   # Comfort Systems USA
    "KNSL",  # Kinsale Capital Group
    "ENSG",  # Ensign Group
    "SCI",   # Service Corp International
    "TREX",  # Trex Company
    "LNTH",  # Lantheus Holdings
    "SITE",  # SiteOne Landscape Supply
    "CSWI",  # CSW Industrials
    "MTN",   # Vail Resorts
    "OLN",   # Olin Corp
    "RMBS",  # Rambus Inc
    "WTS",   # Watts Water Technologies
    "FLR",   # Fluor Corp
    "CW",    # Curtiss-Wright
    "ESAB",  # ESAB Corp
    "BRBR",  # BellRing Brands
    "HWC",   # Hancock Whitney
    "PIPR",  # Piper Sandler
    "BWXT",  # BWX Technologies
    "DOCS",  # Doximity
    "CVLT",  # Commvault Systems
    "MIDD",  # Middleby Corp
    "UFPI",  # UFP Industries
    "MEDP",  # Medpace Holdings
    "TMHC",  # Taylor Morrison Home
    "ONTO",  # Onto Innovation
    "AVTR",  # Avantor Inc
    "MMSI",  # Merit Medical Systems
    "RNR",   # RenaissanceRe Holdings
    "TENB",  # Tenable Holdings
    "GLOB",  # Globant SA
    "GBCI",  # Glacier Bancorp
    "CALX",  # Calix Inc
    "SNDR",  # Schneider National
    "CHDN",  # Churchill Downs
    "ASGN",  # ASGN Inc
    "PLNT",  # Planet Fitness
    "NUVB",  # Nuvation Bio
    "AXSM",  # Axsome Therapeutics
    "ITRI",  # Itron Inc
    "SPSC",  # SPS Commerce
    "OGN",   # Organon & Co
    "WEX",   # WEX Inc
    "LANC",  # Lancaster Colony
    "AIT",   # Applied Industrial Technologies
    "WHD",   # Cactus Inc
    "NMIH",  # NMI Holdings
    "TRNO",  # Terreno Realty
    "POWI",  # Power Integrations
    "ALTR",  # Altair Engineering
    "MHO",   # M/I Homes
    "QLYS",  # Qualys Inc
    "TTEK",  # Tetra Tech
    "BECN",  # Beacon Roofing Supply
    "HAE",   # Haemonetics
    "PRI",   # Primerica
    "LFUS",  # Littelfuse
    "COKE",  # Coca-Cola Consolidated
    "MDGL",  # Madrigal Pharmaceuticals
    "SWX",   # Southwest Gas Holdings
    "HUBG",  # Hub Group
    "FHI",   # Federated Hermes
    "BCC",   # Boise Cascade
    "EXPO",  # Exponent Inc
    "HALO",  # Halozyme Therapeutics
    "LITE",  # Lumentum Holdings
    "OLED",  # Universal Display Corp
    "RGEN",  # Repligen Corp
    "BJ",    # BJ's Wholesale Club
    "GTLS",  # Chart Industries
    "WDFC",  # WD-40 Company
    "DT",    # Dynatrace
]

# ─────────────────────────────────────────────────────────────────────────────
# Small-Cap 성장주 — Russell 2000 고성장 종목 50개 (2025년 기준)
# ─────────────────────────────────────────────────────────────────────────────
SMALL_CAP_GROWTH: list[str] = [
    "IONQ",  # IonQ (양자 컴퓨팅)
    "JOBY",  # Joby Aviation (eVTOL)
    "AFRM",  # Affirm Holdings (BNPL)
    "UPST",  # Upstart Holdings (AI 대출)
    "AEHR",  # Aehr Test Systems (반도체 테스트)
    "LUNR",  # Intuitive Machines (우주)
    "DNA",   # Ginkgo Bioworks (합성 생물학)
    "SOUN",  # SoundHound AI
    "BTDR",  # Bitdeer Technologies (크립토 마이닝)
    "ASTS",  # AST SpaceMobile (위성 통신)
    "MNDY",  # monday.com (워크 매니지먼트)
    "GTLB",  # GitLab (DevOps)
    "BRZE",  # Braze Inc (고객 참여)
    "CELH",  # Celsius Holdings (에너지 음료)
    "HIMS",  # Hims & Hers Health (텔레헬스)
    "SG",    # Sweetgreen (레스토랑)
    "CAVA",  # CAVA Group (레스토랑)
    "BROS",  # Dutch Bros (커피)
    "ASPN",  # Aspen Aerogels (단열재)
    "RXRX",  # Recursion Pharmaceuticals (AI 신약)
    "CLSK",  # CleanSpark (비트코인 마이닝)
    "MARA",  # Marathon Digital Holdings (비트코인 마이닝)
    "RIOT",  # Riot Platforms (비트코인 마이닝)
    "ARQT",  # Arcutis Biotherapeutics (피부과)
    "VKTX",  # Viking Therapeutics (비만 치료)
    "VERA",  # Vera Therapeutics (신장 질환)
    "GERN",  # Geron Corp (종양학)
    "ACHR",  # Archer Aviation (eVTOL)
    "ASAN",  # Asana Inc (프로젝트 관리)
    "BIGC",  # BigCommerce (이커머스)
    "DLO",   # DLocal (이머징 결제)
    "APLS",  # Apellis Pharmaceuticals (안과)
    "ENVX",  # Enovis (정형외과 → 오류 아닌 Enovix 배터리)
    "RELY",  # Remitly Global (해외 송금)
    "VERX",  # Vertex Inc (세금 SW)
    "XPEL",  # XPEL Inc (자동차 보호 필름)
    "SFM",   # Sprouts Farmers Market (유기농 식품)
    "GSAT",  # Globalstar (위성 통신)
    "IREN",  # Iris Energy (데이터센터/마이닝)
    "ME",    # 23andMe (유전자 검사)
    "GRAB",  # Grab Holdings (동남아 슈퍼앱)
    "CIFR",  # Cipher Mining (비트코인 마이닝)
    "PSNY",  # Polestar Automotive (EV)
    "CFLT",  # Confluent (데이터 스트리밍)
    "DKNG",  # DraftKings (스포츠 베팅)
    "PATH",  # UiPath (RPA)
    "BILL",  # BILL Holdings (핀테크)
    "TASK",  # TaskUs (BPO)
    "LMND",  # Lemonade (인슈어테크)
    "CWAN",  # Clearwater Analytics (핀테크)
]


# ─────────────────────────────────────────────────────────────────────────────
# 전체 종목 리스트 (중복 제거 + 정렬)
# ─────────────────────────────────────────────────────────────────────────────
ALL_TICKERS: list[str] = sorted(
    set(NASDAQ_100 + SP500 + POPULAR_ETFS + MID_CAP + SMALL_CAP_GROWTH)
)


# ─────────────────────────────────────────────────────────────────────────────
# 각 티커가 속한 카테고리 인덱스
# {ticker: ["NASDAQ100", "SP500", "ETF", "MIDCAP", "SMALLCAP"]} 형태
# ─────────────────────────────────────────────────────────────────────────────
TICKER_INDEX: dict[str, list[str]] = {}
_nasdaq_set = set(NASDAQ_100)
_sp500_set = set(SP500)
_etf_set = set(POPULAR_ETFS)
_midcap_set = set(MID_CAP)
_smallcap_set = set(SMALL_CAP_GROWTH)

for _t in ALL_TICKERS:
    _indices: list[str] = []
    if _t in _nasdaq_set:
        _indices.append("NASDAQ100")
    if _t in _sp500_set:
        _indices.append("SP500")
    if _t in _etf_set:
        _indices.append("ETF")
    if _t in _midcap_set:
        _indices.append("MIDCAP")
    if _t in _smallcap_set:
        _indices.append("SMALLCAP")
    TICKER_INDEX[_t] = _indices

# 임시 변수 정리
del _nasdaq_set, _sp500_set, _etf_set, _midcap_set, _smallcap_set


def get_tickers_by_index(index_name: str) -> list[str]:
    """특정 인덱스/카테고리 소속 티커 리스트 반환

    지원 카테고리: NASDAQ100, SP500, ETF, MIDCAP, SMALLCAP, ALL
    """
    _map = {
        "NASDAQ100": NASDAQ_100,
        "SP500": SP500,
        "ETF": POPULAR_ETFS,
        "MIDCAP": MID_CAP,
        "SMALLCAP": SMALL_CAP_GROWTH,
    }
    source = _map.get(index_name.upper())
    if source is not None:
        return sorted(set(source))
    return ALL_TICKERS


if __name__ == "__main__":
    print(f"NASDAQ 100:        {len(set(NASDAQ_100)):>4}개")
    print(f"S&P 500:           {len(set(SP500)):>4}개")
    print(f"주요 ETF:          {len(set(POPULAR_ETFS)):>4}개")
    print(f"MidCap:            {len(set(MID_CAP)):>4}개")
    print(f"SmallCap Growth:   {len(set(SMALL_CAP_GROWTH)):>4}개")
    print(f"전체 (중복 제거):  {len(ALL_TICKERS):>4}개")
    print()

    # 카테고리 간 중복 분석
    overlap_nq_sp = set(NASDAQ_100) & set(SP500)
    print(f"NASDAQ100 ∩ SP500:     {len(overlap_nq_sp)}개")
    overlap_etf_sp = set(POPULAR_ETFS) & set(SP500)
    print(f"ETF ∩ SP500:           {len(overlap_etf_sp)}개")
    overlap_mid_sp = set(MID_CAP) & set(SP500)
    print(f"MidCap ∩ SP500:        {len(overlap_mid_sp)}개")
    overlap_small_sp = set(SMALL_CAP_GROWTH) & set(SP500)
    print(f"SmallCap ∩ SP500:      {len(overlap_small_sp)}개")
    print()

    # 카테고리별 개수
    for cat in ["NASDAQ100", "SP500", "ETF", "MIDCAP", "SMALLCAP"]:
        cnt = sum(1 for v in TICKER_INDEX.values() if cat in v)
        print(f"TICKER_INDEX['{cat}']: {cnt}개")
