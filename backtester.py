import re
from datetime import datetime

def parse_log():
    trades = []
    with open('real_cron.log', 'r') as f:
        for line in f:
            if 'Executing STRAT' in line:
                match = re.search(r'Executing (STRAT\d) bet: \$(\d+\.\d+) USDT', line)
                if match:
                    strat = match.group(1)
                    size = float(match.group(2))
                    trades.append({'strat': strat, 'size': size, 'time': datetime.now()})
    print(f"Total trades parsed: {len(trades)}")
    print(f"Strat1 bets: {len([t for t in trades if t['strat'] == 'STRAT1'])}")
    print(f"Strat2 bets: {len([t for t in trades if t['strat'] == 'STRAT2'])}")
    print(f"Average bet size: ${sum(t['size'] for t in trades)/len(trades):.2f}" if trades else "No trades")

parse_log()
