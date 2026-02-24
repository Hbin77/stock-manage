import sys
import logging
from loguru import logger 

logging.basicConfig(level=logging.DEBUG)
logger.add(sys.stdout, level="DEBUG")

print("Starting test")
try:
    from analysis.ai_analyzer import ai_analyzer
    print("Import successful")
    
    tickers = ai_analyzer.get_priority_tickers(5)
    print("Priority Tickers:", tickers)
    
    if not tickers:
        print("No tickers found!")
        sys.exit(0)
        
    for t in tickers:
        print(f"Testing {t}")
        res = ai_analyzer.analyze_ticker(t)
        print("Result:", res)
        
except Exception as e:
    print("Exception:", str(e))
print("Finished test")
